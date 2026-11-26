#자동 업데이트: GitHub 최신 릴리스를 보고, 새 버전이면 Setup 파일을 받아 조용히 설치하고 앱을 다시 켠다
import hashlib, json, os, re, subprocess, threading, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.environ.get("MANGA_DATA_DIR") or ROOT
REPO = "yusuklee/FastManga"
ASSET = re.compile(r"^Install-FastManga\.exe$")
INSTALLED = os.path.isfile(os.path.join(ROOT, "unins000.exe"))   # Setup 으로 깐 것 (포터블 zip 이면 릴리스 페이지만 연다)


def current_version():
    try:
        return open(os.path.join(ROOT, "version.txt"), encoding="utf-8").read().strip()
    except OSError:
        return "dev"


def vtuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)


status = {"state": "idle", "current": current_version(), "latest": None, "url": None, "page": f"https://github.com/{REPO}/releases/latest",
          "size": 0, "pct": None, "text": "", "installed": INSTALLED}
_lock = threading.Lock()


def _get(url, raw=False):
    r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "FastManga", "Accept": "application/vnd.github+json"}), timeout=15)
    return r if raw else json.load(r)


#최신 릴리스 확인. 새 버전이면 status["latest"] 와 Setup 파일 주소를 채운다
def check():
    if status["current"] == "dev":
        return status
    try:
        rel = _get(f"https://api.github.com/repos/{REPO}/releases/latest")
        tag = rel.get("tag_name", "")
        status.update(latest=tag.lstrip("v"), page=rel.get("html_url") or status["page"], url=None, size=0, sha=None)
        for a in rel.get("assets", []):
            if ASSET.match(a["name"]):
                status.update(url=a["browser_download_url"], size=a.get("size", 0), name=a["name"])
            elif a["name"] == "SHA256SUMS.txt":
                status["sha"] = a["browser_download_url"]
        status["available"] = vtuple(status["latest"]) > vtuple(status["current"]) and bool(status["url"])
    except Exception as e:   # noqa: BLE001
        status.update(available=False, text=str(e)[:200])
    return status


def _run():
    try:
        tmp = os.path.join(DATA, "tmp")
        os.makedirs(tmp, exist_ok=True)
        exe = os.path.join(tmp, status["name"])
        status.update(state="downloading", text="Downloading update", pct=0)
        with _get(status["url"], raw=True) as r, open(exe, "wb") as f:
            total = int(r.headers.get("Content-Length") or status["size"] or 0)
            got = 0
            h = hashlib.sha256()
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                got += len(chunk)
                status["pct"] = int(100 * got / total) if total else None
        if status.get("sha"):
            sums = _get(status["sha"], raw=True).read().decode("utf-8", "replace")
            want = next((l.split()[0] for l in sums.splitlines() if l.strip().endswith(status["name"])), None)
            if want and want.lower() != h.hexdigest():
                raise RuntimeError("Downloaded file is corrupted (checksum mismatch)")
        status.update(state="installing", text="Installing update", pct=None)
        launch = os.path.join(ROOT, "python", "pythonw.exe")
        cmd = f'start "" /wait "{exe}" /SILENT /NORESTART /SUPPRESSMSGBOXES & start "" "{launch}" "{os.path.join(ROOT, "launch.py")}"'
        #명령은 문자열로 넘긴다. 리스트로 넘기면 파이썬이 따옴표를 \" 로 바꿔서 cmd 가 못 읽는다 ("'\\'을(를) 찾을 수 없습니다" 창이 뜨고 설치가 안 됨, 11-26)
        subprocess.Popen("cmd /c " + cmd, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0), close_fds=True)
        threading.Timer(1.0, lambda: os._exit(0)).start()   # 설치 파일이 앱 파일을 바꿀 수 있게 앱을 끈다
    except Exception as e:   # noqa: BLE001
        print(f"[update] failed: {type(e).__name__}: {e}", flush=True)
        status.update(state="error", text=str(e)[:300], pct=None)


def install():
    with _lock:
        if status["state"] in ("downloading", "installing"):
            return status
        if not status.get("available") or not INSTALLED:
            status.update(state="error", text="No update available" if not status.get("available") else "Portable version: download the new zip from GitHub")
            return status
        status.update(state="downloading", text="Starting", pct=0)
        threading.Thread(target=_run, daemon=True).start()
    return status
