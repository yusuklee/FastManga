#배포본 만들기: dist/Install-FastManga.exe (Inno Setup) + dist/runtime.zip.001.. (미리 풀어 둔 AI 패키지. 첫 실행 때 앱이 받는다)
#사용: python build/build.py [버전] [--no-runtime]   (runtime 묶음은 5분쯤 걸려서 빼고 빌드할 수 있다)
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

VERSION = "0.2.0"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
APP = os.path.join(DIST, "FastManga", "app")   # 설치 파일에 들어갈 내용
CACHE = os.path.join(ROOT, "build", "cache")
PY_VERSION = "3.13.11"
PY_URL = f"https://www.python.org/ftp/python/{PY_VERSION}/python-{PY_VERSION}-embed-amd64.zip"
PIP_URL = "https://bootstrap.pypa.io/pip/pip.pyz"
TORCH_INDEX = "https://download.pytorch.org/whl/cu128"
ISCC = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe")
PART = 1_900_000_000   # GitHub 릴리스 파일당 2GB 제한


def fetch(url, dest):
    if not os.path.isfile(dest):
        urllib.request.urlretrieve(url, dest)
    return dest


def main(version, runtime=True):
    os.makedirs(CACHE, exist_ok=True)
    shutil.rmtree(os.path.dirname(APP), ignore_errors=True)
    os.makedirs(APP)

    # 1) 파이썬
    zip_path = fetch(PY_URL, os.path.join(CACHE, os.path.basename(PY_URL)))
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(os.path.join(APP, "python"))
    major_minor = "".join(PY_VERSION.split(".")[:2])
    with open(os.path.join(APP, "python", f"python{major_minor}._pth"), "w", encoding="utf-8") as f:
        f.write(f"python{major_minor}.zip\n.\n..\n..\\pylib_boot\nimport site\n")   # ..=app 폴더 (launch.py, backend.py, Process/)
    shutil.copy2(fetch(PIP_URL, os.path.join(CACHE, "pip.pyz")), os.path.join(APP, "pip.pyz"))

    # 2) 앱 코드와 리소스
    for f in ["launch.py", "backend.py", "projects.py", "requirements.txt", "requirements-models.txt", "comictextdetector.pt.onnx", "anime-manga-big-lama.pt"]:
        shutil.copy2(os.path.join(ROOT, f), os.path.join(APP, f))
    shutil.copytree(os.path.join(ROOT, "Process"), os.path.join(APP, "Process"), ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(os.path.join(ROOT, "frontend", "dist"), os.path.join(APP, "frontend", "dist"))
    shutil.copytree(os.path.join(ROOT, "fonts"), os.path.join(APP, "fonts"), ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(os.path.join(ROOT, "models"), os.path.join(APP, "models"))   # 효과음 스타일 모델 (sfx_ar.pt)
    with open(os.path.join(APP, "version.txt"), "w", encoding="utf-8") as f:   # 자동 업데이트·runtime 주소가 쓰는 현재 버전
        f.write(version)

    # 3) 진행 창용 pywebview 만 미리 설치
    py = os.path.join(APP, "python", "python.exe")
    boot = os.path.join(APP, "pylib_boot")
    common = ["--target", boot, "--no-warn-script-location", "--disable-pip-version-check", "--no-cache-dir", "-q"]
    subprocess.run([py, os.path.join(APP, "pip.pyz"), "install", "setuptools", "wheel", *common], check=True)
    subprocess.run([py, os.path.join(APP, "pip.pyz"), "install", "pywebview==6.2.1", "--no-build-isolation", *common], check=True)

    # 4) pip 으로 받을 때의 크기 (진행 막대의 분모. runtime 묶음을 못 받을 때만 pip 을 쓴다)
    write_download_total(py, os.path.join(APP, "requirements.txt"), [])
    write_download_total(py, os.path.join(APP, "requirements-models.txt"), ["--index-url", TORCH_INDEX, "--extra-index-url", "https://pypi.org/simple"])

    # 5) 설치 파일
    if os.path.isfile(ISCC):
        subprocess.run([ISCC, "/Q", f"/DVersion={version}", os.path.join(ROOT, "build", "installer.iss")], check=True)
        exe = os.path.join(DIST, "Install-FastManga.exe")
        print(f"installer: {exe}  ({os.path.getsize(exe) / 1e6:.0f} MB)")
    else:
        print("Inno Setup not found, installer skipped:", ISCC)

    # 6) AI 패키지 묶음: 깨끗한 폴더에 pip 으로 깔고 zip 으로 묶어 2GB 조각으로 나눈다
    if runtime:
        build_runtime(py)
    print(f"release assets (tag v{version}): Install-FastManga.exe + runtime.zip.001, .002")


def build_runtime(py):
    target = os.path.join(CACHE, "runtime_pylib")
    shutil.rmtree(target, ignore_errors=True)
    subprocess.run([py, os.path.join(APP, "pip.pyz"), "install", "--target", target, "-r", os.path.join(APP, "requirements-models.txt"),
                    "--index-url", TORCH_INDEX, "--extra-index-url", "https://pypi.org/simple", "--no-build-isolation",
                    "--no-warn-script-location", "--disable-pip-version-check", "-q"], check=True)
    whole = os.path.join(DIST, "runtime.zip")
    with zipfile.ZipFile(whole, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as z:
        for b, _, fs in os.walk(target):
            for f in fs:
                path = os.path.join(b, f)
                z.write(path, os.path.relpath(path, target))
    for old in [f for f in os.listdir(DIST) if f.startswith("runtime.zip.")]:
        os.remove(os.path.join(DIST, old))
    n = 0
    with open(whole, "rb") as src:
        while True:
            chunk = src.read(PART)
            if not chunk:
                break
            n += 1
            with open(f"{whole}.{n:03d}", "wb") as dst:
                dst.write(chunk)
    size = os.path.getsize(whole)
    os.remove(whole)
    print(f"runtime: {size / 1e9:.2f} GB in {n} parts")


def write_download_total(py, req, index):
    report = os.path.join(tempfile.gettempdir(), "fm_pip_report.json")
    subprocess.run([py, os.path.join(APP, "pip.pyz"), "install", "--dry-run", "--report", report, "-r", req, *index,
                    "--no-build-isolation", "--disable-pip-version-check", "-q"], check=True)
    urls = [i["download_info"]["url"] for i in json.load(open(report, encoding="utf-8"))["install"]]
    total = 0
    for url in urls:
        r = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "pip/26.0"})   # UA 없으면 download.pytorch.org 가 403
        try:
            with urllib.request.urlopen(r, timeout=30) as resp:
                total += int(resp.headers.get("Content-Length") or 0)
        except Exception as e:   # noqa: BLE001
            print("  size unknown:", url[-60:], e)
    with open(req + ".total", "w") as f:
        f.write(str(total))
    print(f"  {os.path.basename(req)}: {len(urls)} files, {total / 1e9:.2f} GB")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(args[0] if args else VERSION, runtime="--no-runtime" not in sys.argv)
