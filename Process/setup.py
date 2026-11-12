import os
import subprocess
import threading
import importlib.util
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from Process.update import current_version
from Process.hayai import REPO as HAYAI_REPO, REV as HAYAI_REV, PROC_REPO, PROC_REV, PATTERNS as HAYAI_PATTERNS, PROC_PATTERNS

ROOT = os.path.dirname(os.path.dirname(__file__))
PYTHON = os.path.join(ROOT, "python", "python.exe")
PIP = os.path.join(ROOT, "pip.pyz")
PACKAGES = os.path.join(ROOT, "packages")

CORE_REQ = os.path.join(ROOT, "requirements.txt")
MODEL_REQ = os.path.join(ROOT, "requirements-models.txt")

TORCH_LOCATION = "https://download.pytorch.org/whl/cu128"
RUNTIME_URL = "https://huggingface.co/yusuklee/FastManga-runtime/resolve/main/runtime.zip"
TMP = os.path.join(ROOT, "tmp")


HAS_PYTHON = os.path.isfile(PYTHON)




def installed(req):
    return os.path.exists(os.path.join(PACKAGES, os.path.basename(req)+".installed"))


def pip_install(req, progress, torch_server=True):
    os.makedirs(PACKAGES, exist_ok=True)
    cmd = [PYTHON, PIP, "install", "-r", req, "--target", PACKAGES, "--upgrade",
           "--progress-bar", "raw", "--no-cache-dir", "--no-build-isolation", "--no-compile"]
    if torch_server:
        cmd += ["--index-url", TORCH_LOCATION, "--extra-index-url", "https://pypi.org/simple"]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace",
                               creationflags=subprocess.CREATE_NO_WINDOW)
    last = watch_download(process, progress)
    if process.wait() != 0:
        raise RuntimeError("Package install failed: " + last)

    open(os.path.join(PACKAGES, os.path.basename(req)+".installed"), "w").close()





def watch_download(process, progress):
    progress("Downloading packages", None)
    last = ""
    for line in map(str.strip, process.stdout):
        if line.startswith("Progress "):
            n, total = int(line.split()[1]), int(line.split()[3])
            progress("Downloading packages", int(100 * n / total))
        elif line.startswith("Installing collected"):
            progress("Installing packages", None)
        elif line:
            last = line
    return last




#downloaded: zip 을 다 받은 뒤 부른다 (풀기는 CPU 라 그동안 인터넷이 놀아서, 여기서 모델 받기를 시작한다)
def install_runtime(progress, downloaded=lambda: None):
    os.makedirs(TMP, exist_ok=True)
    os.makedirs(PACKAGES, exist_ok=True)
    dest = os.path.join(TMP, "runtime.zip")
    got = 0
    with urllib.request.urlopen(RUNTIME_URL, timeout=30) as r, open(dest, "wb") as f:
        total = int(r.headers["Content-Length"])
        while chunk := r.read(1 << 20):
            f.write(chunk)
            got += len(chunk)
            progress(f"Downloading PyTorch  {got / 1e9:.1f} GB / {total / 1e9:.1f} GB", int(100 * got / total))
    downloaded()
    # 앱(pythonw.exe) 안에서 풀면 python.exe 보다 2배 느려서 python.exe 로 푼다
    process = subprocess.Popen([PYTHON, "-c", "import sys; from Process.setup import unpack; unpack(sys.argv[1])", dest],
                               cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW)
    last = ""
    for line in map(str.strip, process.stdout):
        if line.isdigit():
            progress("Installing PyTorch", int(line))
        elif line:
            last = line
    if process.wait() != 0:
        raise RuntimeError("runtime unpack failed: " + last)
    os.remove(dest)
    open(os.path.join(PACKAGES, os.path.basename(MODEL_REQ) + ".installed"), "w").close()


def unpack(dest):
    with zipfile.ZipFile(dest) as z:
        infos = z.infolist()
    for d in {os.path.dirname(os.path.join(PACKAGES, i.filename)) for i in infos}:
        os.makedirs(d, exist_ok=True)
    zips, sources, local = [], [], threading.local()
    def extract(info):
        if not hasattr(local, "zip"):
            local.zip = zipfile.ZipFile(dest)
            zips.append(local.zip)
        path = local.zip.extract(info, PACKAGES)
        if path.endswith(".pyc"):   # pyc 에 적힌 원본 .py 수정 시간. 풀면서 바뀐 .py 시간을 이걸로 되돌려야 pyc 가 쓰인다
            with open(path, "rb") as f:
                mtime = int.from_bytes(f.read(12)[8:], "little")
            name = os.path.basename(path).split(".")[0] + ".py"
            sources.append((os.path.join(os.path.dirname(os.path.dirname(path)), name), mtime))
        return info.file_size
    full = sum(i.file_size for i in infos)
    done = 0
    with ThreadPoolExecutor(16) as ex:
        for k, size in enumerate(ex.map(extract, infos)):
            done += size
            if k % 200 == 0:
                print(int(100 * done / full), flush=True)
    for z in zips:
        z.close()
    for src, mtime in sources:
        if os.path.exists(src):
            os.utime(src, (mtime, mtime))


def install_model_packages(progress, downloaded=lambda: None):
    if current_version() != "dev":
        try:
            return install_runtime(progress, downloaded)
        except Exception as e:
            print(f"[setup] runtime bundle failed ({type(e).__name__}: {e}), falling back to pip", flush=True)
    pip_install(MODEL_REQ, progress)


def models_downloaded():
    from huggingface_hub import snapshot_download
    try:
        for repo, patterns, rev in HF_MODELS:
            snapshot_download(repo, revision=rev, allow_patterns=patterns, local_files_only=True)
        return True
    except Exception:
        return False



HF_MODELS = [
    ("mayocream/koharu-layout-rfdetr-seg-2xl-1152", ["model.safetensors"], None),  #RF-DETR
    (HAYAI_REPO, HAYAI_PATTERNS, HAYAI_REV),   #OCR
    (PROC_REPO, PROC_PATTERNS, PROC_REV), #HAYAI 전처리기
]






def download_models(progress):
    from huggingface_hub import  snapshot_download
    from tqdm.auto import tqdm

    class Bar(tqdm):
        def update(self, n=1):
            super().update(n)
            if self.unit != "B":
                return
            progress(f"Downloading models  {int(self.n / 1e9)} GB / {int(self.total / 1e9)} GB", int(100 * self.n / self.total))
    for repo, patterns, ver in HF_MODELS:
        snapshot_download(repo, revision=ver, allow_patterns=patterns, tqdm_class=Bar)




def packages_ready():
    if HAS_PYTHON:
        return installed(MODEL_REQ)
    return all(importlib.util.find_spec(m) is not None for m in ("torch", "rfdetr", "transformers", "onnxruntime"))


status = {"state": "idle", "text": "", "pct": None}
_lock = threading.Lock()


def progress(text, pct):
    status.update(state="working", text=text, pct=pct)


#모델 받기를 런타임 풀기와 동시에 한다 (2026-11-08 측정: 받기 57초 → 풀기 27초 ∥ 모델 21초, 차례로보다 약 20초 빠름.
#런타임 받기와 동시에 받으면 인터넷을 나눠 써서 8초만 줄어든다). 풀기 동안 진행 표시는 풀기 쪽만
def _run():
    pool = ThreadPoolExecutor(1)
    try:
        models = []
        unpacking = threading.Event()
        def quiet(text, pct):
            if not unpacking.is_set():
                progress(text, pct)
        def start_models():
            if not models and not models_downloaded():
                models.append(pool.submit(download_models, quiet))
        def downloaded():   # 런타임 zip 을 다 받음 → 풀기와 동시에 모델을 받는다
            unpacking.set()
            start_models()
        if not packages_ready():
            install_model_packages(progress, downloaded)
        unpacking.clear()
        start_models()   # 런타임이 이미 있었거나 pip 로 깔았으면 여기서
        for m in models:
            m.result()
        progress("Loading models", None)
        from Process.detect_ocr import get_rfdetr
        get_rfdetr()
        status.update(state="ready", text="", pct=None)
    except Exception as e:
        print(f"[setup] failed: {type(e).__name__}: {e}", flush=True)
        status.update(state="error", text=str(e)[:300], pct=None)
    finally:
        pool.shutdown(wait=False)


def ready():
    return status["state"] == "ready"


def prepare():
    with _lock:
        if status["state"] in ("working", "ready"):
            return
        status.update(state="working", text="Checking", pct=None)
        threading.Thread(target=_run, daemon=True).start()
