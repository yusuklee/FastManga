#배포본 실행 파일. 첫 실행이면 기본 패키지를 받고, 백엔드를 띄운 뒤 창에 연다. AI 패키지·모델은 앱 안에서 처음 PROCESS 할 때 받는다
import os
import socket
import sys
import threading
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("MANGA_DATA_DIR") or ROOT
PYLIB = os.path.join(DATA, "pylib")


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
    for p in (os.path.join(DATA, "pylib_models"), PYLIB):   # 기본 패키지(pylib)가 앞
        if p not in sys.path:
            sys.path.insert(0, p)


def free_port():
    with socket.socket() as s:
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
            if not setup.installed(setup.CORE_REQ):
                setup.pip_install(setup.CORE_REQ, self.set)
            if not setup.installed(setup.MODEL_REQ):   # PyTorch/CUDA 등 3GB. 모델 파일은 처음 PROCESS 때
                setup.install_model_packages(self.set)
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
    $("sub").textContent = s.error ? s.text : (s.text.startsWith("Downloading") || s.text.startsWith("Installing")) ? "First start only." : "";
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
