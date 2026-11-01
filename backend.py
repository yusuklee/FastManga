from fastapi import FastAPI, UploadFile, Form, Response, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from PIL import Image
import io, os, json
from Process.detect_ocr import detect_boxes, ocr_boxes, paddle_prepare, paddle_status
from Process.translate import req_and_fill_res, local_prepare, local_status
from Process.inpaint import inpaint_lama
from fonts.fonts import list_korean_fonts, FONTS_DIR
from google.genai import errors as genai_errors
ROOT = os.path.dirname(__file__)

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


#인페인팅 결과는 PNG 바이트 그대로 보낸다 (base64 JSON 보다 1/3 작고, 프런트가 디코드할 필요 없음)
def png_response(out):
    buf = io.BytesIO()
    out.save(buf, format="PNG", compress_level=1)   # 압축 낮게 = 빠르게. 브라우저로 가는 임시 결과라 용량보다 속도
    return Response(buf.getvalue(), media_type="image/png")


@app.post("/detect")
async def detect(file: UploadFile, classes: str = Form("text")):
    wanted = tuple(c.strip() for c in classes.split(",") if c.strip()) or ("text",)
    return detect_boxes(Image.open(io.BytesIO(await file.read())), wanted)


@app.post("/ocr")
async def ocr_route(file: UploadFile, contents: str = Form(...), ocr: str = Form("hayai")):
    return ocr_boxes(Image.open(io.BytesIO(await file.read())), json.loads(contents), ocr)


@app.post("/paddle_ocr/prepare")
def paddle_ocr_prepare():
    paddle_prepare()
    return paddle_status


@app.get("/paddle_ocr/status")
def paddle_ocr_status():
    return paddle_status


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


#LaMa
@app.post("/inpaint_lama")
async def inpaint_lama_route(file: UploadFile, contents: str = Form(...)):
    return png_response(inpaint_lama(Image.open(io.BytesIO(await file.read())), json.loads(contents)))


@app.post("/sfx_render")
async def sfx_render_route(file: UploadFile, erased: UploadFile, contents: str = Form(...)):
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


#LaMa 는 처음 쓸 때 올라온다. 프런트가 "모델 불러오는 중" 표시에 쓴다
@app.get("/models")
def models():
    from Process import inpaint
    return {"lama": inpaint._lama is not None}


if os.path.isdir(FONTS_DIR):
    app.mount("/fontfiles", StaticFiles(directory=FONTS_DIR), name="fontfiles")

@app.get("/fonts")
def fonts():
    return list_korean_fonts() if os.path.isdir(FONTS_DIR) else []


#프로젝트 저장 (코하루식 디스크 저장): /projects/... — projects.py
from projects import router as projects_router
app.include_router(projects_router)


#PyInstaller 로 묶이면 sys._MEIPASS(임시 풀림 폴더) 아래에 있다
def resource_dir():
    import sys
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))

FRONTEND_DIST = os.path.join(resource_dir(), "frontend", "dist")
if os.path.isdir(FRONTEND_DIST):
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
