import os
import subprocess
import threading
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from Process.update import current_version

ROOT = os.path.dirname(os.path.dirname(__file__))
PYTHON = os.path.join(ROOT, "python", "python.exe")
PIP = os.path.join(ROOT, "pip.pyz")
PACKAGES = os.path.join(ROOT, "packages")

CORE_REQ = os.path.join(ROOT, "requirements.txt")
MODEL_REQ = os.path.join(ROOT, "requirements-models.txt")

TORCH_LOCATION = "https://download.pytorch.org/whl/cu128"
RUNTIME_URL = "https://huggingface.co/yusuklee/FastManga-runtime/resolve/main/runtime.zip"
TMP = os.path.join(ROOT, "tmp")



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
        try:
            path = local.zip.extract(info, PACKAGES)
        except PermissionError:   # 앱이 쓰고 있는 파일 (모델을 받는 중인 hf_xet.pyd). 기본 패키지로 이미 깔린 같은 버전이라 건너뛴다
            path = os.path.join(PACKAGES, info.filename)
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


status = {"state": "idle", "text": "", "pct": None}
_lock = threading.Lock()


def progress(text, pct):
    status.update(state="working", text=text, pct=pct)


#PROCESS 를 처음 누를 때: 탐지 모델을 메모리에 올린다. AI 패키지와 모델 파일은 앱을 켤 때 launch.py 가 이미 받았다
def _run():
    try:
        progress("Loading models", None)
        from Process.detect_ocr import get_rfdetr
        get_rfdetr()
        status.update(state="ready", text="", pct=None)
    except Exception as e:
        print(f"[setup] failed: {type(e).__name__}: {e}", flush=True)
        status.update(state="error", text=str(e)[:300], pct=None)


def ready():
    return status["state"] == "ready"


def prepare():
    with _lock:
        if status["state"] in ("working", "ready"):
            return
        status.update(state="working", text="Checking", pct=None)
        threading.Thread(target=_run, daemon=True).start()
