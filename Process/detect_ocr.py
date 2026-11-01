import warnings, logging
warnings.filterwarnings("ignore")
logging.disable(logging.WARNING)

import os, re, base64, io, time, atexit, threading, subprocess
from concurrent.futures import ThreadPoolExecutor
import requests
import numpy as np
import cv2
from PIL import Image
from dotenv import load_dotenv
from huggingface_hub import hf_hub_download
from safetensors.torch import load_file
from rfdetr import RFDETRSeg2XLarge

load_dotenv()

HAS_TEXT = re.compile(r'[ぁ-んァ-ヶ一-龯가-힣0-9A-Za-z]')

_rfdetr = None


def get_rfdetr():
    global _rfdetr
    if _rfdetr is None:
        m = RFDETRSeg2XLarge(pretrain_weights=None, resolution=1152, num_select=160, num_classes=4)
        m.model.model.load_state_dict(
            load_file(hf_hub_download("mayocream/koharu-layout-rfdetr-seg-2xl-1152", "model.safetensors"), device="cpu"),
            strict=True,
        )
        m.model.class_names = ["text", "onomatopoeia", "bubble", "panel"]
        _rfdetr = m
    return _rfdetr


get_rfdetr()


PADDLE_REPO = "PaddlePaddle/PaddleOCR-VL-1.6-GGUF"
PADDLE_FILES = ("PaddleOCR-VL-1.6-GGUF.gguf", "PaddleOCR-VL-1.6-GGUF-mmproj.gguf")
PADDLE_PORT = 8791
PADDLE_SLOTS = 4
paddle_status = {"state": "idle", "text": "", "done": 0, "total": 0}   # idle / downloading / starting / ready / error
_paddle_proc = None
_paddle_lock = threading.Lock()


def paddle_running():
    return _paddle_proc is not None and _paddle_proc.poll() is None


def paddle_stop():
    global _paddle_proc
    from Process.translate import kill_port
    if paddle_running():
        _paddle_proc.terminate()
        _paddle_proc.wait(10)
    _paddle_proc = None
    kill_port(PADDLE_PORT)   # 이전 서버가 남긴 고아 프로세스까지

atexit.register(paddle_stop)


def paddle_ensure():
    global _paddle_proc
    from Process.translate import download, llama_exe, GGUF_DIR, LLAMA_DIR
    with _paddle_lock:
        if paddle_running():
            return
        try:
            paddle_stop()   # 포트에 남은 이전 프로세스 정리
            exe = llama_exe()
            paths = [os.path.join(GGUF_DIR, f) for f in PADDLE_FILES]
            for f, path in zip(PADDLE_FILES, paths):
                download(f"https://huggingface.co/{PADDLE_REPO}/resolve/main/{f}", path, f, paddle_status)
            paddle_status.update(state="starting", text="PaddleOCR-VL", done=0, total=0)
            log = open(os.path.join(LLAMA_DIR, "ocr_server.log"), "w", encoding="utf-8")
            _paddle_proc = subprocess.Popen([exe, "-m", paths[0], "--mmproj", paths[1], "--host", "127.0.0.1", "--port", str(PADDLE_PORT),
                                             "-np", str(PADDLE_SLOTS), "-c", str(4096 * PADDLE_SLOTS), "--reasoning-budget", "0"],
                                            stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
            t = time.time()
            while True:
                if _paddle_proc.poll() is not None:
                    raise RuntimeError("OCR server stopped (see llama/ocr_server.log)")
                try:
                    if requests.get(f"http://127.0.0.1:{PADDLE_PORT}/health", timeout=2).ok:
                        break
                except requests.RequestException:
                    pass
                if time.time() - t > 300:
                    raise RuntimeError("OCR server did not start in 5 minutes")
                time.sleep(0.5)
            paddle_status.update(state="ready", text="PaddleOCR-VL")
        except Exception as e:
            paddle_status.update(state="error", text=str(e))
            raise


#프런트가 detect 전에 부른다: 바로 돌아가고 받기·띄우기는 뒤에서. 진행은 paddle_status 로
def paddle_prepare():
    if paddle_running():
        paddle_status.update(state="ready", text="PaddleOCR-VL")
        return
    paddle_status.update(state="starting", text="PaddleOCR-VL", done=0, total=0)
    threading.Thread(target=paddle_ensure, daemon=True).start()


JP_SPACE = re.compile(r"(?<=[ぁ-んァ-ヶ一-龯ー、。「」！？])\s+(?=[ぁ-んァ-ヶ一-龯ー、。「」！？])")   # 일본어 글자 사이 공백은 뺀다 (한국어·영어 띄어쓰기는 유지)

def _paddle_one(crop):
    buf = io.BytesIO()
    crop.save(buf, "PNG")
    r = requests.post(f"http://127.0.0.1:{PADDLE_PORT}/v1/chat/completions", json={
        "messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()}},
                                                  {"type": "text", "text": "OCR:"}]}],
        "temperature": 0, "max_tokens": 512}, timeout=600)
    r.raise_for_status()
    text = re.sub(r"\s+", " ", r.json()["choices"][0]["message"]["content"]).strip()
    return JP_SPACE.sub("", text)


def paddle_ocr(crops):
    if not crops:
        return []
    paddle_ensure()
    with ThreadPoolExecutor(PADDLE_SLOTS) as ex:
        return list(ex.map(_paddle_one, crops))


def ocr_texts(crops, ocr="hayai"):
    if ocr == "paddle":
        return paddle_ocr(crops)
    from Process import hayai
    return hayai.recognize(crops)


def ocr_boxes(image, boxes, ocr="hayai"):
    image = image.convert("RGB")
    arr = np.array(image)
    W, H = image.size
    text_boxes = [(max(0, int(b["pos"][0])), max(0, int(b["pos"][1])), min(W, int(b["pos"][2])), min(H, int(b["pos"][3]))) for b in boxes]

    prob, line_map = get_word_line_maps(image)
    page_mask = filter_expand_ctd_mask(prob)
    ink = (np.array(image.convert("L")) < 100) & page_mask       # 실제 잉크 픽셀 (줄 나누기용)

    n, labels, stats, _ = cv2.connectedComponentsWithStats(page_mask.astype(np.uint8))
    bbox = {i: (int(x), int(y), int(x + w), int(y + h)) for i, (x, y, w, h, a) in enumerate(stats) if i > 0}

    erase_boxes = [expand_RF(labels, bbox, pos) for pos in text_boxes]
    words = ocr_texts([image.crop(pos) for pos in text_boxes], ocr)

    lines = []
    for b, pos, erase, word in zip(boxes, text_boxes, erase_boxes, words):
        if not HAS_TEXT.search(word):
            if not b.get("user"):
                continue
            word = ""
        ex1, ey1, ex2, ey2 = erase
        color, stroke = text_colors(arr, page_mask, pos)   # 지우기 상자(erase)는 옆 글자 획까지 끌어안을 수 있어 원래 상자에서 잰다
        lines.append({
            **({"id": b["id"]} if "id" in b else {}),
            "pos": pos,
            "mask_area": erase,
            "word": word,
            "page": 1,
            "mask": mask_to_text(page_mask[ey1:ey2, ex1:ex2]),
            "bubble": b.get("bubble"),
            **({"user": True} if b.get("user") else {}),
            **({"sfx": True} if b.get("sfx") else {}),
            "font_size": font_size(line_map, ink, pos),
            "angle": text_angle(line_map, page_mask, pos),
            "color": color,
            "stroke": stroke,
        })
    return lines


#종류별 신뢰도 하한. 의성어는 모양이 제각각이라 점수가 낮게 나오니 더 낮게 받는다
THRESHOLDS = {"text": 0.3, "onomatopoeia": 0.2, "bubble": 0.5}

#DETECT: RF-DETR 로 글자 상자·말풍선만 찾는다 (OCR 없음). id 는 0 부터, word 는 빈 문자열
def detect_boxes(file, classes=("text",)):
    image = file.convert("RGB")
    d = get_rfdetr().predict(image, threshold=min(THRESHOLDS.values()))
    keep = [(tuple(max(0, int(v)) for v in b), n) for b, n, s in zip(d.xyxy, d.data["class_name"], d.confidence) if s >= THRESHOLDS.get(n, 0.5)]
    text_boxes = [b for b, n in keep if n in classes]
    bubbles = [b for b, n in keep if n == "bubble"]
    sfx = [n == "onomatopoeia" for _, n in keep if n in classes]
    return [{"id": i, "pos": p, "bubble": bub, "word": "", "page": 1, **({"sfx": True} if s else {})}
            for i, (p, bub, s) in enumerate(zip(text_boxes, assign_bubbles(text_boxes, bubbles), sfx))]


def text_colors(arr, page_mask, box):
    x1, y1, x2, y2 = box
    crop, m = arr[y1:y2, x1:x2].astype(np.float32), page_mask[y1:y2, x1:x2]
    if m.sum() < 20 or (~m).sum() < 20:
        return "#000000", None
    ring = (cv2.dilate(m.astype(np.uint8), square(6)) > 0) & ~m     # 글자 바로 둘레 띠 = 글자의 실제 배경 (상자 전체 배경은 다른 색이 섞임)
    bg = np.median(crop[ring], axis=0) if ring.sum() >= 20 else np.median(crop[~m], axis=0)
    far = m & (np.linalg.norm(crop - bg, axis=2) > 60)
    if far.sum() < 20:
        return "#000000", None
    hexc = lambda c: "#%02x%02x%02x" % tuple(int(round(v)) for v in c)
    px = crop[far]
    lum = 0.299 * px[:, 0] + 0.587 * px[:, 1] + 0.114 * px[:, 2]
    dm = np.median(px[lum <= np.percentile(lum, 35)], axis=0)
    lm = np.median(px[lum >= np.percentile(lum, 65)], axis=0)
    if np.linalg.norm(dm - lm) > 110:
        near_d = np.linalg.norm(crop - dm, axis=2) < np.linalg.norm(crop - lm, axis=2)
        d_mask, l_mask = far & near_d, far & ~near_d
        if min(d_mask.sum(), l_mask.sum()) >= 0.25 * far.sum():
            touch = cv2.dilate((~far).astype(np.uint8), square(1)) > 0     # 배경(또는 글자 아닌 곳)과 맞닿은 픽셀
            d_touch = (d_mask & touch).sum() / d_mask.sum()
            l_touch = (l_mask & touch).sum() / l_mask.sum()
            fill, stroke = (lm, dm) if d_touch > l_touch else (dm, lm)
            #테두리 후보가 채움색과 배경색의 중간색이면 테두리가 아니라 가장자리 번짐(안티에일리어싱)
            seg = bg - fill
            t = np.clip(np.dot(stroke - fill, seg) / max(np.dot(seg, seg), 1e-6), 0, 1)
            if np.linalg.norm(stroke - (fill + t * seg)) > 40:
                return hexc(fill), hexc(stroke)
    return hexc(np.median(px, axis=0)), None


def assign_bubbles(boxes, bubbles):
    def owner(box):
        cx, cy = (box[0] + box[2]) // 2, (box[1] + box[3]) // 2
        hit = [b for b in bubbles if b[0] <= cx <= b[2] and b[1] <= cy <= b[3]]
        return min(hit, key=lambda b: (b[2] - b[0]) * (b[3] - b[1])) if hit else None
    owners = [owner(b) for b in boxes]
    shared = {b for b in owners if b is not None and owners.count(b) > 1}
    return [None if b in shared else b for b in owners]


def expand_RF(labels, bbox, box):
    x1, y1, x2, y2 = box
    for i in set(np.unique(labels[y1:y2, x1:x2])) - {0}:
        bx1, by1, bx2, by2 = bbox[i]
        x1, y1, x2, y2 = min(x1, bx1), min(y1, by1), max(x2, bx2), max(y2, by2)
    return (x1, y1, x2, y2)



CTD_MODEL = os.environ.get("CTD_MODEL", "comictextdetector.pt.onnx")
CTD_SIZE = 1024
BINARY_THRESHOLD = 60 / 255
CLOSE_RADIUS = 10
DILATE_RADIUS = 3

_ctd = None
def get_ctd():
    global _ctd
    if _ctd is None:
        import torch          # torch 가 묶어 온 CUDA/cuDNN DLL 을 먼저 올려야 onnxruntime-gpu 가 GPU 를 잡음
        import onnxruntime as ort
        path = CTD_MODEL
        if not os.path.exists(path):
            path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), CTD_MODEL)
        _ctd = ort.InferenceSession(path, providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
    return _ctd


def get_word_line_maps(image):
    W, H = image.size
    s = CTD_SIZE / max(W, H)
    rw, rh = round(W * s), round(H * s)

    canvas = np.zeros((CTD_SIZE, CTD_SIZE, 3), np.uint8)
    canvas[:rh, :rw] = np.array(image.convert("RGB").resize((rw, rh)))
    inp = canvas.transpose(2, 0, 1)[None].astype(np.float32) / 255.0

    _, word, line = get_ctd().run(None, {"images": inp})
    up = lambda m: cv2.resize(m[:rh, :rw], (W, H), interpolation=cv2.INTER_LINEAR)
    return up(word[0, 0]), up(line[0, 0])


def square(r):
    return np.ones((2 * r + 1, 2 * r + 1), np.uint8)


def filter_expand_ctd_mask(ctd_mask):
    m = (ctd_mask >= BINARY_THRESHOLD).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, square(CLOSE_RADIUS))
    return cv2.dilate(m, square(DILATE_RADIUS)) > 0


def mask_to_text(mask_box):
    buf = io.BytesIO()
    Image.fromarray(mask_box.astype(np.uint8)*255).save(buf,format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


#DEF of cutting box (for ocr) by lines

LINE_THRESHOLD = 0.5
MIN_LINE_AREA = 50       # 이보다 작은 심지는 잡음


def thickness(box):
    return min(box[2] - box[0], box[3] - box[1])


#상자가 클떄 상자를 여러개로 쪼개서 돌려주는 함수
def cut_box(line_map, ink, box): #ink 는 줄 마스크  영역
    x1, y1, x2, y2 = box
    box_and_lines = (line_map[y1:y2, x1:x2] >= LINE_THRESHOLD).astype(np.uint8)
    _, _, st, _ = cv2.connectedComponentsWithStats(box_and_lines)
    cut_lines = [(int(x), int(y), int(x + w), int(y + h)) for x, y, w, h, a in st[1:] if a >= MIN_LINE_AREA]
    if not cut_lines:
        return []

    sub_ink = ink[y1:y2, x1:x2]
    W, H = x2 - x1, y2 - y1
    out = []
    for cx1, cy1, cx2, cy2 in cut_lines:
        vertical = (cy2 - cy1) > (cx2 - cx1)  #세로 줄이라고 판단
        thick = (cx2 - cx1) if vertical else (cy2 - cy1)
        if vertical:
            lo, hi = 0, W                                   # 가로 한계: 옆 심지와의 중간
            for ox1, oy1, ox2, oy2 in cut_lines:
                if (ox1, oy1, ox2, oy2) == (cx1, cy1, cx2, cy2) or oy1 >= cy2 or oy2 <= cy1:
                    continue
                if ox2 <= cx1:
                    lo = max(lo, (ox2 + cx1) // 2)
                elif ox1 >= cx2:
                    hi = min(hi, (ox1 + cx2) // 2)
            win = sub_ink[max(0, cy1 - thick):min(H, cy2 + thick), lo:hi]
            ox, oy = lo, max(0, cy1 - thick)
        else:
            lo, hi = 0, H
            for ox1, oy1, ox2, oy2 in cut_lines:
                if (ox1, oy1, ox2, oy2) == (cx1, cy1, cx2, cy2) or ox1 >= cx2 or ox2 <= cx1:
                    continue
                if oy2 <= cy1:
                    lo = max(lo, (oy2 + cy1) // 2)
                elif oy1 >= cy2:
                    hi = min(hi, (oy1 + cy2) // 2)
            win = sub_ink[lo:hi, max(0, cx1 - thick):min(W, cx2 + thick)]
            ox, oy = max(0, cx1 - thick), lo
        ys, xs = np.nonzero(win)
        if xs.size == 0:
            out.append((x1 + cx1, y1 + cy1, x1 + cx2, y1 + cy2))
        else:
            out.append((x1 + ox + int(xs.min()), y1 + oy + int(ys.min()),
                        x1 + ox + int(xs.max()) + 1, y1 + oy + int(ys.max()) + 1))
    return out


BIG_GLYPH = 80

def glyph_size(ink, box):
    x1, y1, x2, y2 = box
    _, _, st, _ = cv2.connectedComponentsWithStats(ink[y1:y2, x1:x2].astype(np.uint8))
    sizes = [max(w, h) for x, y, w, h, a in st[1:] if a >= 20]
    return int(np.percentile(sizes, 90)) if sizes else 0


#길쭉하지 않은 덩어리·세로 줄은 빼고, 3도 미만은 0 (멀쩡한 대사가 삐뚤어지지 않게)
def text_angle(line_map, mask, box):
    x1, y1, x2, y2 = box
    comp = (line_map[y1:y2, x1:x2] >= LINE_THRESHOLD).astype(np.uint8)
    n, labels, st, _ = cv2.connectedComponentsWithStats(comp)
    sub = mask[y1:y2, x1:x2]
    angles, weights = [], []
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] < MIN_LINE_AREA:
            continue
        ys, xs = np.nonzero(sub & (labels == i))
        if len(xs) < 50:
            continue
        pts = np.stack([xs, ys], 1).astype(np.float32)
        ev, evec = np.linalg.eigh(np.cov((pts - pts.mean(0)).T))
        if ev[1] < 6 * max(ev[0], 1e-6):   # 길이가 높이의 2.5배는 돼야 방향이 믿을 만하다
            continue
        a = np.degrees(np.arctan2(evec[1, 1], evec[0, 1]))
        a = a - 180 if a > 90 else a + 180 if a <= -90 else a
        if abs(a) > 45:   # 세로 줄
            continue
        angles.append(a)
        weights.append(len(xs))
    if not angles:
        return 0
    order = np.argsort(angles)
    cum = np.cumsum(np.array(weights)[order])
    a = float(np.array(angles)[order][np.searchsorted(cum, cum[-1] / 2)])
    return round(a, 1) if abs(a) >= 3 else 0


def font_size(line_map, ink, box):
    g = glyph_size(ink, box)
    if g >= BIG_GLYPH:
        return g
    lines = cut_box(line_map, ink, box)
    return int(np.median([thickness(l) for l in lines])) if lines else thickness(box)
