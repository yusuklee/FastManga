#설치: 첫 실행(launch.py) 때 기본 패키지(requirements.txt)와 AI 패키지(requirements-models.txt: 릴리스의 runtime.zip 묶음,
#못 받으면 pip), 처음 PROCESS 할 때 모델(Hugging Face). torch 같은 무거운 것은 import 하지 않는다
import fnmatch, hashlib, importlib, importlib.util, os, re, shutil, subprocess, sys, threading, time, urllib.error, urllib.request, zipfile
from Process.update import current_version

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.environ.get("MANGA_DATA_DIR") or ROOT
PYTHON = os.path.join(ROOT, "python", "python.exe")
PIP = os.path.join(ROOT, "pip.pyz")
PYLIB = os.path.join(DATA, "pylib")
PYLIB_MODELS = os.path.join(DATA, "pylib_models")   # AI 패키지는 따로: 앱이 도는 중에 깔아도 쓰는 중인 파일을 안 건드린다
TMP = os.path.join(DATA, "tmp")
CORE_REQ = os.path.join(ROOT, "requirements.txt")
MODEL_REQ = os.path.join(ROOT, "requirements-models.txt")
TORCH_INDEX = "https://download.pytorch.org/whl/cu128"
from Process.hayai import REPO as HAYAI_REPO, REV as HAYAI_REV, PROC_REPO, PROC_REV, PATTERNS as HAYAI_PATTERNS, PROC_PATTERNS
HF_MODELS = [
    ("mayocream/koharu-layout-rfdetr-seg-2xl-1152", ["model.safetensors"], None),
    (HAYAI_REPO, HAYAI_PATTERNS, HAYAI_REV),
    (PROC_REPO, PROC_PATTERNS, PROC_REV),
]
PORTABLE = os.path.isfile(PYTHON)   # 배포본(동봉 python) 인지. 개발 PC 면 conda env 를 그대로 쓴다
INSTALL_SIZE = {CORE_REQ: 350_000_000, MODEL_REQ: 5_400_000_000}   # 다 풀렸을 때 폴더 크기 (설치 단계 진행률의 분모)
#미리 풀어서 묶어 둔 AI 패키지 (build.py 가 만들고 릴리스에 runtime.zip.001, .002 로 올린다). 2GB 제한 때문에 조각
RUNTIME_URL = os.environ.get("FASTMANGA_RUNTIME_URL") or f"https://github.com/yusuklee/FastManga/releases/download/v{current_version()}/runtime.zip"


def _hash(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _mark(req):
    return os.path.join(PYLIB if req == CORE_REQ else PYLIB_MODELS, ".installed")


def installed(req):
    try:
        return open(_mark(req), encoding="utf-8").read().strip() == _hash(req)
    except OSError:
        return False


def download_total(req):
    try:
        return int(open(req + ".total").read().strip())
    except (OSError, ValueError):
        return 0


def fmt_bytes(n):
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


class PipProgress:
    """pip --progress-bar raw 출력에서 받은 바이트 수를 센다"""
    SIZE = re.compile(r"\((\d+(?:\.\d+)?)\s*(kB|MB|GB|bytes)\)")
    UNIT = {"bytes": 1, "kB": 1e3, "MB": 1e6, "GB": 1e9}

    def __init__(self):
        self.done = self.cur = 0

    def feed(self, line):
        if line.startswith("Progress "):
            m = re.match(r"Progress (\d+) of (\d+)", line)
            if m:
                self.cur = int(m.group(1))
            return
        if ".metadata" in line:
            return
        if line.startswith(("Downloading ", "Using cached ")):
            self.done += self.cur
            self.cur = 0
            if line.startswith("Using cached"):
                m = self.SIZE.search(line)
                self.done += int(float(m.group(1)) * self.UNIT[m.group(2)]) if m else 0

    @property
    def got(self):
        return self.done + self.cur


#pip 으로 req 를 설치 (기본 → pylib, AI → pylib_models). report(text, pct) 로 진행을 알린다
def pip_install(req, report, torch_index=False):
    target = PYLIB if req == CORE_REQ else PYLIB_MODELS
    os.makedirs(target, exist_ok=True)
    index = ["--index-url", TORCH_INDEX, "--extra-index-url", "https://pypi.org/simple"] if torch_index else []
    cmd = [PYTHON, PIP, "install", "--target", target, "--upgrade", "-r", req, *index,
           "--no-warn-script-location", "--progress-bar", "raw", "--disable-pip-version-check", "--no-build-isolation", "--no-cache-dir"]
    total = download_total(req)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP)
    env = dict(os.environ, TMPDIR=TMP, TEMP=TMP, TMP=TMP)
    report("Downloading packages", 0)
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", creationflags=flags, env=env)
    progress, tail, installing = PipProgress(), [], threading.Event()
    base = dir_size(target)

    #사용자에겐 막대 하나: 다운로드가 0~60%, 푸는 단계가 60~100%
    def watch_install():   # pip --target 은 TMP\pip-target-* 에 먼저 풀고 끝에 target 으로 옮긴다 → 둘을 합쳐 잰다
        while not installing.wait(1):
            pass
        while p.poll() is None:
            try:
                size = dir_size(target) - base + sum(dir_size(os.path.join(TMP, d)) for d in os.listdir(TMP) if d.startswith("pip-target-"))
            except OSError:   # 끝나면서 TMP 가 지워짐
                break
            report("Installing packages", min(99, 60 + int(40 * size / INSTALL_SIZE[req])))
            time.sleep(1)

    threading.Thread(target=watch_install, daemon=True).start()
    for line in p.stdout:
        line = line.strip()
        if not line:
            continue
        tail = (tail + [line])[-30:]
        if not line.startswith("Progress "):
            print("[pip]", line, flush=True)
        if line.startswith("Installing collected"):
            installing.set()
            report("Installing packages", 60)
        elif not installing.is_set():
            progress.feed(line)
            got = min(progress.got, total) if total else progress.got
            report(f"Downloading packages  {fmt_bytes(got)}" + (f" / {fmt_bytes(total)}" if total else ""), int(60 * got / total) if total else None)
    if p.wait() != 0:
        err = [l for l in tail if re.match(r"^\w*(Error|Exception)\b", l)]
        raise RuntimeError("Package install failed: " + (err[-1] if err else tail[-1]))
    shutil.rmtree(TMP, ignore_errors=True)
    with open(_mark(req), "w", encoding="utf-8") as f:
        f.write(_hash(req))
    importlib.invalidate_caches()


def _open(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "FastManga"}), timeout=30)


#릴리스의 runtime.zip 조각들을 받아 이어 붙이고 pylib_models 에 푼다. 다운로드 0~60%, 풀기 60~100%
def install_runtime(report):
    sizes = []
    while True:
        try:
            with _open(f"{RUNTIME_URL}.{len(sizes) + 1:03d}") as r:
                sizes.append(int(r.headers.get("Content-Length") or 0))
        except (urllib.error.HTTPError, urllib.error.URLError, FileNotFoundError):
            break
    if not sizes:
        raise RuntimeError("runtime bundle not found")
    total = sum(sizes)
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP)
    dest = os.path.join(TMP, "runtime.zip")
    got = 0
    with open(dest, "wb") as f:
        for i in range(len(sizes)):
            with _open(f"{RUNTIME_URL}.{i + 1:03d}") as r:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    report(f"Downloading PyTorch  {fmt_bytes(got)} / {fmt_bytes(total)}", int(60 * got / total) if total else None)
    shutil.rmtree(PYLIB_MODELS, ignore_errors=True)
    os.makedirs(PYLIB_MODELS)
    with zipfile.ZipFile(dest) as z:
        infos = z.infolist()
        full = sum(i.file_size for i in infos) or 1
        done = 0
        for k, info in enumerate(infos):
            z.extract(info, PYLIB_MODELS)
            done += info.file_size
            if k % 200 == 0:
                report("Installing PyTorch", min(99, 60 + int(40 * done / full)))
    shutil.rmtree(TMP, ignore_errors=True)
    with open(_mark(MODEL_REQ), "w", encoding="utf-8") as f:
        f.write(_hash(MODEL_REQ))
    importlib.invalidate_caches()


#AI 패키지: 릴리스 묶음을 먼저, 안 되면 pip
def install_model_packages(report):
    if current_version() != "dev":
        try:
            return install_runtime(report)
        except Exception as e:   # noqa: BLE001
            print(f"[setup] runtime bundle failed ({type(e).__name__}: {e}), falling back to pip", flush=True)
    pip_install(MODEL_REQ, report, torch_index=True)


def models_downloaded():
    from huggingface_hub import snapshot_download
    try:
        for repo, patterns, rev in HF_MODELS:
            snapshot_download(repo, revision=rev, allow_patterns=patterns, local_files_only=True)
        return True
    except Exception:   # noqa: BLE001
        return False


def dir_size(path):
    total = 0
    for base, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(base, f))
            except OSError:
                pass
    return total


#Hugging Face 모델을 받는다. 진행은 캐시 폴더 크기로 잰다. report(text, pct)
def download_models(report):
    from huggingface_hub import HfApi, constants, snapshot_download
    total = 0
    for repo, patterns, rev in HF_MODELS:
        try:
            for s in HfApi().model_info(repo, revision=rev, files_metadata=True).siblings:
                if any(fnmatch.fnmatch(s.rfilename, pat) for pat in patterns):
                    total += s.size or 0
        except Exception:   # noqa: BLE001
            pass
    base = dir_size(constants.HF_HUB_CACHE)
    done = threading.Event()

    def watch():
        while not done.wait(1):
            got = max(0, dir_size(constants.HF_HUB_CACHE) - base)
            report(f"Downloading models  {fmt_bytes(got)}" + (f" / {fmt_bytes(total)}" if total else ""), min(99, int(100 * got / total)) if total else None)

    report("Downloading models", 0 if total else None)
    threading.Thread(target=watch, daemon=True).start()
    try:
        for repo, patterns, rev in HF_MODELS:
            snapshot_download(repo, revision=rev, allow_patterns=patterns)
    finally:
        done.set()


def packages_ready():
    if PORTABLE:
        return installed(MODEL_REQ)
    return all(importlib.util.find_spec(m) is not None for m in ("torch", "rfdetr", "transformers", "onnxruntime"))


status = {"state": "idle", "text": "", "pct": None}   # idle / working / ready / error
_lock = threading.Lock()


def _report(text, pct):
    status.update(state="working", text=text, pct=pct)


def _run():
    try:
        if not packages_ready():
            install_model_packages(_report)
        if not models_downloaded():
            download_models(_report)
        _report("Loading models", None)
        from Process.detect_ocr import get_rfdetr
        get_rfdetr()
        status.update(state="ready", text="", pct=None)
    except Exception as e:   # noqa: BLE001
        print(f"[setup] failed: {type(e).__name__}: {e}", flush=True)
        status.update(state="error", text=str(e)[:300], pct=None)


def ready():
    return status["state"] == "ready"


#모델 준비를 시작한다 (이미 하는 중이면 그대로). 상태는 status 로 본다
def prepare():
    with _lock:
        if status["state"] in ("working", "ready"):
            return
        status.update(state="working", text="Checking", pct=None)
        threading.Thread(target=_run, daemon=True).start()
