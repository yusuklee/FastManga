from fastapi import FastAPI, UploadFile, Form, Response, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from PIL import Image
import io, os, json
from Process import setup
from Process.translate import req_and_fill_res, local_prepare, local_status
from fonts.fonts import list_korean_fonts, FONTS_DIR
from google.genai import errors as genai_errors
ROOT = os.path.dirname(os.path.abspath(__file__))

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


#처음 PROCESS 할 때 탐지 모델을 메모리에 올린다 (AI 패키지·모델 파일은 앱을 켤 때 launch.py 가 받는다). 그 전엔 탐지·OCR·지우기 라우트가 409 를 돌려준다
@app.post("/setup/prepare")
def setup_prepare():
    setup.prepare()
    return setup.status


@app.get("/setup/status")
def setup_status():
    return setup.status


#자동 업데이트 (Process/update.py)
@app.get("/update/check")
def update_check():
    from Process import update
    return update.check()


@app.post("/update/install")
def update_install():
    from Process import update
    return update.install()


@app.get("/update/status")
def update_status():
    from Process import update
    return update.status


def models():
    if not setup.ready():
        raise HTTPException(409, "AI models are not installed yet")
    from Process import detect_ocr, inpaint
    return detect_ocr, inpaint


#인페인팅 결과는 PNG 바이트 그대로 보낸다 (base64 JSON 보다 1/3 작고, 프런트가 디코드할 필요 없음)
def png_response(out):
    buf = io.BytesIO()
    out.save(buf, format="PNG", compress_level=1)   # 압축 낮게 = 빠르게. 브라우저로 가는 임시 결과라 용량보다 속도
    return Response(buf.getvalue(), media_type="image/png")


@app.post("/detect")
async def detect(file: UploadFile, classes: str = Form("text")):
    wanted = tuple(c.strip() for c in classes.split(",") if c.strip()) or ("text",)
    return models()[0].detect_boxes(Image.open(io.BytesIO(await file.read())), wanted)


@app.post("/ocr")
async def ocr_route(file: UploadFile, contents: str = Form(...), ocr: str = Form("hayai")):
    return models()[0].ocr_boxes(Image.open(io.BytesIO(await file.read())), json.loads(contents), ocr)


@app.post("/paddle_ocr/prepare")
def paddle_ocr_prepare():
    d = models()[0]
    d.paddle_prepare()
    return d.paddle_status


@app.get("/paddle_ocr/status")
def paddle_ocr_status():
    return models()[0].paddle_status


@app.post("/translate")
def translate(body: dict, api_key: str | None = Header(default=None, alias="X-Api-Key")):
    local =body.get("local",False)
    base_url = body.get("base_url")
    if base_url !=None and base_url.strip()=="":
        raise HTTPException(400, "enter the Base URL in Settings")

    if local:
        try:
            return req_and_fill_res(body["lines"], body.get("source", None), body.get("target", "English"),
                                    body.get("model"), local=local)
        except Exception as e:
            c = getattr(e, "code", None)
            raise HTTPException(c if 400 <= (c or 0) <600 else 502, str(e))

    elif body.get("provider") == "claude":
        try:
            return req_and_fill_res(body["lines"], body.get("source", None), body.get("target", "English"),
                                    body.get("model"), api_key=api_key, provider="claude", effort=body.get("effort", "medium"))
        except Exception as e:
            c = getattr(e, "code", None)
            raise HTTPException(c if 400 <= (c or 0) < 600 else 502, str(e))

    elif base_url:
        try:
            return req_and_fill_res(body["lines"], body.get("source", None), body.get("target", "English"),
                                    body.get("model"), base_url=base_url, api_key=api_key)
        except Exception as e:
            c = getattr(e, "code", None)
            raise HTTPException(c if 400 <= (c or 0) < 600 else 502, str(e))

    else:
        try:
            return req_and_fill_res(body["lines"], body.get("source", None), body.get("target", "English"),
                                    body.get("model"), base_url=base_url, api_key=api_key, model2=body.get("model2"))

        except genai_errors.APIError as e:  # 키가 틀리거나(400/403) 한도(429) 등 API 쪽 오류 -> 그 코드와 메시지를 그대로
            raise HTTPException(e.code ,f" Gemini: {e.message}")

        except Exception as e:
            c=getattr(e,"code",None)
            raise HTTPException(c if 400 <= (c or 0) < 600 else 502, str(e))


@app.post("/local_llm/prepare")
def local_llm_prepare(body: dict):
    try:
        local_prepare(body["model"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    return local_status


@app.get("/local_llm/status")
def local_llm_status():
    return local_status


@app.post("/inpaint_lama")
async def inpaint_lama_route(file: UploadFile, contents: str = Form(...)):
    return png_response(models()[1].inpaint_lama(Image.open(io.BytesIO(await file.read())), json.loads(contents)))


#원상복구: 상자들이 지운 자리만 원본(file) 픽셀로 되돌린 erased 를 준다
@app.post("/restore")
async def restore_route(file: UploadFile, erased: UploadFile, contents: str = Form(...)):
    return png_response(models()[1].restore(Image.open(io.BytesIO(await file.read())), Image.open(io.BytesIO(await erased.read())), json.loads(contents)))


@app.post("/sfx_render")
async def sfx_render_route(file: UploadFile, erased: UploadFile, contents: str = Form(...)):
    models()
    from Process.sfx_style import render_page
    return png_response(render_page(Image.open(io.BytesIO(await file.read())), Image.open(io.BytesIO(await erased.read())), json.loads(contents)))


#데스크톱 앱 내보내기: 프런트가 캔버스로 그린 PNG 를 폴더 경로와 함께 보내면 그 폴더에 쓴다.
@app.post("/export")
async def export_file(file: UploadFile, folder: str = Form(...), name: str = Form(...)):
    folder = os.path.abspath(folder)
    if not os.path.isdir(folder):
        raise HTTPException(400, "folder not found")
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "bad file name")
    with open(os.path.join(folder, name), "wb") as f:
        f.write(await file.read())
    return {"ok": True}


@app.post("/api_key")
def save_api_key(api_key:str=Form(...)):
    with open(os.path.join(ROOT, ".env"), "w", encoding="utf-8") as f:
        f.write(f"GEMINI_API_KEY={api_key}\n")
    os.environ["GEMINI_API_KEY"] = api_key


if os.path.isdir(FONTS_DIR):
    app.mount("/fontfiles", StaticFiles(directory=FONTS_DIR), name="fontfiles")

@app.get("/fonts")
def fonts():
    return list_korean_fonts() if os.path.isdir(FONTS_DIR) else []


#프로젝트 저장 (코하루식 디스크 저장): /projects/... — projects.py
from projects import router as projects_router
app.include_router(projects_router)


FRONTEND_DIST = os.path.join(ROOT, "frontend", "dist")
if os.path.isdir(FRONTEND_DIST):
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
