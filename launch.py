#배포본 실행 파일. 첫 실행이면 기본 패키지 → PyTorch 묶음 받기 → 풀기와 동시에 모델 받기를 하고, 백엔드를 띄운 뒤 창에 연다
import os
import socket
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("MANGA_DATA_DIR") or ROOT


def setup_env():
    os.chdir(ROOT)
    os.makedirs(os.path.join(DATA, "logs"), exist_ok=True)
    if sys.stdout is None or sys.stderr is None:   # pythonw: 콘솔이 없다 → 로그 파일로
        log = open(os.path.join(DATA, "logs", "app.log"), "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log
    os.environ["HF_HOME"] = os.path.join(DATA, "hf")
    os.environ.setdefault("MANGA_PROJECTS_DIR", os.path.join(DATA, "projects"))
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    os.environ.setdefault("LAMA_MODEL", os.path.join(ROOT, "anime-manga-big-lama.pt"))
    os.environ.setdefault("CTD_MODEL", os.path.join(ROOT, "comictextdetector.pt.onnx"))
    os.makedirs(os.path.join(ROOT, "packages"), exist_ok=True)   # 없으면 파이썬이 이 경로를 영영 안 봐서 설치 직후 import 가 실패
    sys.path.insert(0, os.path.join(ROOT, "packages"))


#처음 켤 때 허깅페이스에서 받는 모델 (저장소, 받을 파일, 버전)
def hf_models():
    from Process.hayai import REPO, REV, PROC_REPO, PROC_REV, PATTERNS, PROC_PATTERNS
    from Process.sam_mask import REPO as SAM_REPO, REV as SAM_REV, PATTERNS as SAM_PATTERNS
    return [
        ("mayocream/koharu-layout-rfdetr-seg-2xl-1152", ["model.safetensors"], None),   # RF-DETR
        (REPO, PATTERNS, REV),   # OCR (HAYAI, 16비트 314MB)
        (PROC_REPO, PROC_PATTERNS, PROC_REV),   # HAYAI 전처리기
        (SAM_REPO, SAM_PATTERNS, SAM_REV),   # 효과음의 글자 마스크 (SAM 2.1, 16비트 449MB)
    ]


def models_downloaded():
    from huggingface_hub import snapshot_download
    try:
        for repo, patterns, rev in hf_models():
            snapshot_download(repo, revision=rev, allow_patterns=patterns, local_files_only=True)
        return True
    except Exception:   # noqa: BLE001
        return False


#모델 저장소들을 동시에 받는다 (저장소마다 연결을 여는 시간이 겹쳐서 차례로 받는 것보다 빠르다). 진행률은 전부 합쳐서 알린다
def download_models(progress):
    from huggingface_hub import snapshot_download
    from tqdm.auto import tqdm
    bars = {}

    class Bar(tqdm):
        def update(self, n=1):
            super().update(n)
            if self.unit != "B" or not self.total:
                return
            bars[id(self)] = (self.n, self.total)
            got, total = sum(v[0] for v in bars.values()), sum(v[1] for v in bars.values())
            progress(f"Downloading models  {got / 1e9:.1f} GB / {total / 1e9:.1f} GB", int(100 * got / total))
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(lambda m: snapshot_download(m[0], revision=m[2], allow_patterns=m[1], tqdm_class=Bar), hf_models()))


PORT = 47615   # 앱 주소를 켤 때마다 같게: 설정·API 키는 화면의 localStorage 에 있고 주소(포트)별로 따로 저장돼서, 포트가 바뀌면 다 사라진 것처럼 보인다 (11-23)


#고정 포트를 쓰고, 다른 프로그램이 이미 쓰고 있을 때만 빈 포트 (그때는 저장해 둔 설정이 안 보인다)
def free_port():
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", PORT))
        except OSError:
            s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Boot:
    """뒤에서 설치·서버 시작을 하고, 로딩 화면이 status() 를 읽는다"""

    def __init__(self, window, port):
        self.window, self.port = window, port
        self.url = f"http://127.0.0.1:{port}"
        self.state = {"text": "Starting", "pct": None}
        self.lock = threading.Lock()

    def set(self, text, pct=None, error=False):
        with self.lock:
            self.state = {"text": text, "pct": pct, "error": error}

    def status(self):
        with self.lock:
            return dict(self.state)

    def retry(self):
        if self.status().get("error"):
            self.start()
        return True

    def pick_folder(self):
        import webview
        picked = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        return {"path": picked[0]} if picked else None

    def start(self):
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        try:
            from Process import setup
            pool, models, unpacking = ThreadPoolExecutor(2), [], threading.Event()
            core = None
            if not setup.installed(setup.CORE_REQ):   # 기본 패키지는 PyTorch 묶음을 받는 동안 같이 깐다
                core = pool.submit(setup.pip_install, setup.CORE_REQ, lambda text, pct: None, False)
            def quiet(text, pct):   # 풀기 동안 진행 표시는 풀기 쪽만
                if not unpacking.is_set():
                    self.set(text, pct)
            def start_models():
                if core:
                    core.result()   # 모델 받기와 풀기는 기본 패키지가 다 깔린 뒤에
                if not models and not models_downloaded():
                    models.append(pool.submit(download_models, quiet))
            def downloaded():   # PyTorch 묶음을 다 받음 → 푸는 동안 모델을 같이 받는다
                unpacking.set()
                start_models()
            if not setup.installed(setup.MODEL_REQ):   # PyTorch/CUDA 등 3GB
                setup.install_model_packages(self.set, downloaded)
            unpacking.clear()
            start_models()   # PyTorch 묶음이 이미 있었거나 pip 로 깔았으면 여기서
            for m in models:
                m.result()
            self.set("Starting")
            threading.Thread(target=self.serve, daemon=True).start()
            while True:
                try:
                    with urllib.request.urlopen(self.url + "/setup/status", timeout=2) as r:
                        if r.status == 200:
                            break
                except Exception:   # noqa: BLE001  아직 안 떴다
                    pass
                time.sleep(0.5)
            self.window.load_url(self.url)
        except Exception as e:   # noqa: BLE001
            print(f"[launch] failed: {type(e).__name__}: {e}", flush=True)
            self.set(str(e)[:300], error=True)

    def serve(self):
        import uvicorn
        from backend import app
        uvicorn.run(app, host="127.0.0.1", port=self.port, log_level="warning")


def loading_html():
    return """<!doctype html><html><head><meta charset="utf-8"><title>FastManga</title>
<style>
  html,body{height:100%;margin:0;font-family:Segoe UI,system-ui,sans-serif;background:#0a1033;color:#fff}
  .c{height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;padding:0 24px}
  .title{font-size:15px}
  .bar{width:360px;height:8px;border-radius:4px;background:#1c2657;overflow:hidden;position:relative}
  .bar i{display:block;height:100%;width:0;background:#f2760a;transition:width .4s}
  .bar.busy i{width:30%;animation:slide 1.2s infinite ease-in-out}
  @keyframes slide{from{margin-left:-30%}to{margin-left:100%}}
  small{color:#9aa4d6;text-align:center;line-height:1.5;white-space:pre-wrap;max-width:520px}
  button{display:none;margin-top:8px;padding:6px 18px;border:0;border-radius:6px;background:#f2760a;color:#fff;font:inherit;cursor:pointer}
</style></head><body><div class="c">
  <div class="title" id="title">Starting</div>
  <div class="bar busy" id="bar"><i id="fill"></i></div>
  <small id="sub"></small>
  <button id="retry" onclick="retry()">Retry</button>
</div>
<script>
  const $ = id => document.getElementById(id);
  function retry() { $("retry").style.display = "none"; window.pywebview.api.retry(); }
  async function tick() {
    let s;
    try { s = await window.pywebview.api.status(); } catch { return setTimeout(tick, 500); }
    const pct = s.pct ?? null;
    $("title").textContent = s.error ? "Setup failed" : s.text + (pct !== null ? `  ${pct}%` : "");
    $("bar").style.display = s.error ? "none" : "";
    $("bar").classList.toggle("busy", pct === null);
    $("fill").style.width = pct === null ? "" : pct + "%";
    $("sub").textContent = s.error ? s.text : "";
    $("retry").style.display = s.error ? "" : "none";
    setTimeout(tick, 500);
  }
  window.addEventListener("pywebviewready", tick);
</script></body></html>"""


class Api:
    """pywebview 에 노출되는 함수들 (window.pywebview.api.*). Boot 로 넘긴다"""

    def __init__(self):
        self._boot = None

    def status(self):
        return self._boot.status()

    def retry(self):
        return self._boot.retry()

    def pick_folder(self):
        return self._boot.pick_folder()

    def fullscreen(self):
        self._boot.window.toggle_fullscreen()


def main():
    setup_env()
    import webview
    api = Api()
    window = webview.create_window("FastManga", html=loading_html(), js_api=api, width=1400, height=900, min_size=(900, 600))
    api._boot = Boot(window, free_port())
    api._boot.start()
    webview.start(private_mode=False, storage_path=os.path.join(ROOT, "webview"))
    sys.exit(0)


if __name__ == "__main__":
    main()
