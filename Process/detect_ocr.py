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
from rfdetr.models.postprocess import PostProcess

load_dotenv()

HAS_TEXT = re.compile(r'[ぁ-んァ-ヶ一-龯가-힣0-9A-Za-z]')

_rfdetr = None


#RF-DETR 는 후보 160개의 마스크를 전부 페이지 크기로 키운 뒤에 점수 낮은 것을 버린다 (큰 페이지에서 2.8GB)
#점수는 마스크와 상관없이 먼저 정해지므로, 먼저 버리고 남은 것만 키운다 (결과는 같다)
class KeepThenResize(PostProcess):
    def forward(self, outputs, target_sizes):
        import torch
        import torch.nn.functional as F
        logits, masks = outputs["pred_logits"], outputs["pred_masks"]
        results = super().forward({"pred_logits": logits, "pred_boxes": outputs["pred_boxes"]}, target_sizes)   # 마스크 없이: 점수·종류·상자만
        picked = torch.topk(logits.sigmoid().view(logits.shape[0], -1), self.num_select, dim=1)[1] // logits.shape[2]   # 후보마다 몇 번째 마스크인가
        for i, r in enumerate(results):
            keep = r["scores"] > THRESHOLD
            h, w = target_sizes[i].tolist()
            r.update(scores=r["scores"][keep], labels=r["labels"][keep], boxes=r["boxes"][keep],
                     masks=F.interpolate(masks[i][picked[i][keep]].unsqueeze(1), size=(int(h), int(w)), mode="bilinear", align_corners=False) > 0.0)
        return results


def get_rfdetr():
    global _rfdetr
    if _rfdetr is None:
        m = RFDETRSeg2XLarge(pretrain_weights=None, resolution=1152, num_select=160, num_classes=4)
        m.model.model.load_state_dict(
            load_file(hf_hub_download("mayocream/koharu-layout-rfdetr-seg-2xl-1152", "model.safetensors"), device="cpu"),
            strict=True,
        )
        m.model.class_names = ["text", "onomatopoeia", "bubble", "panel"]
        m.model.postprocess = KeepThenResize(num_select=m.model.postprocess.num_select)
        if m.model.device.type == "cuda":
            import torch
            m.optimize_for_inference(compile=False, dtype=torch.float16)
            m.model.model.to("cpu")
            torch.cuda.empty_cache()
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


#조각 그림들을 같은 높이로 맞춰 흰 여백을 두고 가로로 붙인다 (떨어진 글자를 한 단어로 읽게)
def join_crops(crops, h=300, gap=30):
    ims = [c.convert("RGB").resize((max(1, round(c.width * h / c.height)), h)) for c in crops]
    out = Image.new("RGB", (sum(i.width for i in ims) + gap * (len(ims) + 1), h + gap * 2), "white")
    x = gap
    for im in ims:
        out.paste(im, (x, gap))
        x += im.width + gap
    return out


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
    crops = [image.crop(pos) for pos in text_boxes]
    # 사용자가 이은 상자: 순서대로 같은 높이로 맞춰 가로로 이어 붙여 한 번에 읽고, 첫 상자에 넣는다 (나머지는 빈 글자)
    groups = {}
    for i, b in enumerate(boxes):
        if b.get("group") is not None:
            groups.setdefault(b["group"], []).append(i)
    grouped = {i for idx in groups.values() for i in idx}
    solo = [i for i in range(len(crops)) if i not in grouped]
    words = [""] * len(crops)
    for i, w in zip(solo, ocr_texts([crops[i] for i in solo], ocr)):
        words[i] = w
    for idx in groups.values():   # 묶음은 따로 읽는다 (다른 조각과 한 번에 읽으면 결과가 흔들림)
        idx.sort(key=lambda i: boxes[i].get("order") or 0)
        words[idx[0]] = ocr_texts([join_crops([crops[i] for i in idx])], ocr)[0]
    #이은 상자는 상자마다 따로도 읽어 둔다: 효과음 늘이기를 그 상자의 글자 수로 재야 해서 (묶음 글자는 첫 상자에만 들어감)
    box_words = dict(zip(sorted(grouped), ocr_texts([crops[i] for i in sorted(grouped)], ocr))) if grouped else {}

    lines = []
    for i_, (b, pos, erase, word) in enumerate(zip(boxes, text_boxes, erase_boxes, words)):
        if not HAS_TEXT.search(word):
            if not b.get("user") and b.get("group") is None:
                continue
            word = ""
        ex1, ey1, ex2, ey2 = erase
        mask, letter = page_mask[ey1:ey2, ex1:ex2], False
        from Process.sfx_style import stroke_width
        # 글자 마스크 (11-19 결정): 대사는 전부 comic-text-detector, 효과음은 전부 SAM 2.1. 글자색·테두리·굵기를 정하는 방식은 둘이 같다 (enclosed_colors)
        if b.get("sfx"):   # 효과음: SAM 2.1 마스크 → 최적의 직사각형 → 직사각형에서 색 (11-20 결정)
            from Process import sam_mask
            from Process.sfx_style import sfx_colors
            erase, mask = sam_mask.letter_mask(image, pos)   # 지우기도 SAM 2.1 마스크로
            letter = True                                    # 회전·크기도 이 마스크를 감싸는 가장 작은 직사각형으로 정한다 (11-19 결정: 탐지기가 잡은 상자도 사람이 그린 상자와 같게)
            color, stroke, stroke_w, glyph = sfx_colors(image, pos)
            size = 0
        else:              # 대사: RF-DETR 상자에서 색
            count = len("".join(word.split()))   # 글자 크기 (11-19 결정): 글자 상자 넓이 ÷ 글자 수 의 제곱근 (글자 하나가 차지하는 정사각형의 한 변). 글자가 없으면 예전 방식(글자 줄 굵기)
            size = round(((pos[2] - pos[0]) * (pos[3] - pos[1]) / count) ** 0.5) if count else 0
            color, stroke, stroke_w, glyph = enclosed_colors(arr, pos, page_mask)
        lines.append({
            **({"id": b["id"]} if "id" in b else {}),
            "pos": pos,
            "mask_area": erase,
            "word": word,
            "page": 1,
            "mask": mask_to_text(mask),
            "bubble": b.get("bubble"),
            **({"bubble_area": b["bubble_area"], "bubble_mask": b["bubble_mask"]} if b.get("bubble_mask") else {}),
            **({"user": True} if b.get("user") else {}),
            **({"letter": True} if letter else {}),   # mask 가 글자 모양 그대로(선+속)다 → 효과음 렌더가 이 마스크로 색·굵기·기울기를 잰다
            **({"sfx": True} if b.get("sfx") else {}),
            **({"group": b["group"], "order": b.get("order"), "box_word": box_words.get(i_, "")} if b.get("group") is not None else {}),
            "font_size": size or font_size(line_map, ink, pos),
            "angle": text_angle(line_map, page_mask, pos),
            "color": color,
            "stroke": stroke,
            "stroke_width": stroke_w,        # 테두리 굵기(px). 테두리가 없으면 None
            "thick": stroke_width(glyph),    # 획 굵기(px). 프런트가 번역문 획을 이 굵기에 맞춘다
        })
    return lines


THRESHOLD = 0.5   # 신뢰도 하한 (글자·의성어·말풍선 모두)


#같은 말풍선 안에서 옆으로 붙은 세로줄(위아래가 반 이상 겹치고 사이가 줄 폭보다 좁음)은 한 문장이 쪼개져 잡힌 것 → 한 상자로
#(위아래로 떨어진 두 대사는 그대로 둔다)
def merge_columns(boxes, owners, sfx):
    boxes, owners, sfx = list(boxes), list(owners), list(sfx)
    def joined(a, b):
        gap = max(b[0] - a[2], a[0] - b[2])
        overlap = min(a[3], b[3]) - max(a[1], b[1])
        return gap < min(a[2] - a[0], b[2] - b[0]) and overlap > 0.5 * min(a[3] - a[1], b[3] - b[1])
    i = 0
    while i < len(boxes):
        j = next((j for j in range(i + 1, len(boxes)) if owners[i] and owners[j] == owners[i] and not sfx[i] and not sfx[j] and joined(boxes[i], boxes[j])), None)
        if j is None:
            i += 1
            continue
        a, b = boxes[i], boxes.pop(j); owners.pop(j); sfx.pop(j)
        boxes[i] = (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))
    return boxes, owners, sfx


#DETECT: RF-DETR 로 글자 상자·말풍선만 찾는다 (OCR 없음). id 는 0 부터, word 는 빈 문자열
def detect_boxes(file, classes=("text",)):
    image = file.convert("RGB")
    d = get_rfdetr().predict(image, threshold=THRESHOLD)
    keep = [(tuple(max(0, int(v)) for v in b), n, k) for k, (b, n) in enumerate(zip(d.xyxy, d.data["class_name"]))]
    text_boxes = [b for b, n, _ in keep if n in classes]
    shapes = {b: d.mask[k] for b, n, k in keep if n == "bubble"}   # 말풍선 실제 모양 (페이지 크기)
    sfx = [n == "onomatopoeia" for _, n, _ in keep if n in classes]
    owners = assign_bubbles(text_boxes, shapes)
    text_boxes, owners, sfx = merge_columns(text_boxes, owners, sfx)
    # bubble: 글자가 든 말풍선 (렌더 영역. 여럿이 같이 쓰면 프런트가 나눈다). bubble_area/bubble_mask: 말풍선 모양 (지우기·폭 재기)
    return [{"id": i, "pos": p, "bubble": o,
             **({"bubble_area": o, "bubble_mask": mask_to_text(shapes[o][o[1]:o[3], o[0]:o[2]])} if o else {}),
             "word": "", "page": 1, **({"sfx": True} if s else {})}
            for i, (p, o, s) in enumerate(zip(text_boxes, owners, sfx))]


def snap_color(c):   # 어두우면 검정, 밝으면 흰색으로 맞춘다
    l = 54 * c[0] + 183 * c[1] + 19 * c[2]
    return (0, 0, 0) if l <= 64 * 256 else (255, 255, 255) if l >= 191 * 256 else tuple(int(round(v)) for v in c)


def color_between(c, a, b):   # c 가 a 와 b 를 섞은 색인가 (글자 가장자리가 번진 색)
    seg = b - a
    t = np.dot(c - a, seg) / max(np.dot(seg, seg), 1e-6)
    return 0 <= t <= 1 and ((c - a - t * seg) ** 2).sum() <= 24 * 24 * 3


#대사 글자색·테두리 (11-15 결정). 글자 상자를 2px 넓혀 그 안 픽셀을 4가지 색으로 묶는다(바탕, 가장 어두운 색, 가장 밝은 색, 그 셋과 가장 먼 색).
#한 색을 벽으로 쳤을 때 상자 가장자리에서 닿을 수 없는(갇힌) 다른 색이 있으면 갇힌 색 = 글자색, 벽 색 = 테두리색.
#후보가 여럿이면 (두 색의 차이) × (갇힌 픽셀 중 글자 마스크 안에 있는 수) 가 가장 큰 쪽. 갇힌 색이 없으면 바탕과 가장 다른 색이 글자색, 테두리 없음.
#letter: 페이지 크기 글자 마스크 (SAM 2.1 둘째 후보). 갇힌 색을 찾는 방식은 Koharu 의 detection.rs 를 따랐다
#→ (글자색, 테두리색 또는 None, 테두리 굵기 px 또는 None, 글자색으로 본 픽셀(넓힌 상자 크기 bool)). 효과음 렌더(sfx_style.measure)도 이걸 쓴다
def enclosed_colors(arr, box, letter):
    H, W = arr.shape[:2]
    x1, y1, x2, y2 = max(0, box[0] - 2), max(0, box[1] - 2), min(W, box[2] + 2), min(H, box[3] + 2)
    crop, ins = arr[y1:y2, x1:x2].astype(np.int64), letter[y1:y2, x1:x2]
    h, w = crop.shape[:2]
    if h < 5 or w < 5:
        return "#000000", None, None, np.zeros((h, w), bool)
    hexc = lambda c: "#%02x%02x%02x" % snap_color(c)
    dist2 = lambda a, b: float(((a - b) ** 2).sum())
    lum = lambda c: 54 * c[:, 0] + 183 * c[:, 1] + 19 * c[:, 2]
    med = lambda m: np.median(crop[m], axis=0)
    band = np.ones((h, w), bool)
    band[2:-2, 2:-2] = False
    seed = np.median(crop[band], axis=0)   # 가장자리 2px 띠의 가운데값 = 바탕색
    px = crop.reshape(-1, 3)
    _, inv, cnt = np.unique((px[:, 0] >> 4) * 256 + (px[:, 1] >> 4) * 16 + (px[:, 2] >> 4), return_inverse=True, return_counts=True)   # 색을 채널마다 16단계로 줄여 모은다
    pal = np.zeros((len(cnt), 3))
    np.add.at(pal, inv, px)
    pal /= cnt[:, None]
    ok = np.nonzero(cnt >= 4)[0] if (cnt >= 4).any() else np.arange(len(cnt))
    centers = [seed, pal[ok[np.argmin(lum(pal[ok]))]], pal[ok[np.argmax(lum(pal[ok]))]]]
    far = np.min([((pal - c) ** 2).sum(1) for c in centers], axis=0) * np.minimum(cnt, 64)
    centers = np.array(centers + [pal[np.argmax(far)]], float)
    for _ in range(4):   # 가까운 색끼리 묶기를 4번
        near = np.argmin(((pal[:, None] - centers[None]) ** 2).sum(2), axis=1)
        for k in range(4):
            if (near == k).any():
                centers[k] = (pal[near == k] * cnt[near == k, None]).sum(0) / cnt[near == k].sum()
    lab = np.argmin(((px[:, None].astype(float) - centers[None]) ** 2).sum(2), axis=1).reshape(h, w)   # 픽셀마다 몇 번 색인가
    used = [k for k in range(4) if (lab == k).any()]
    back = min(used, key=lambda k: dist2(centers[k], seed))
    bg = med(lab == back)
    best = None
    for s in used:
        wall = lab == s
        if s == back or wall.sum() < 8:
            continue
        _, comp = cv2.connectedComponents(np.pad(~wall, 1, constant_values=True).astype(np.uint8), connectivity=4)
        outside = (comp == comp[0, 0])[1:-1, 1:-1]   # 벽을 못 넘고 상자 가장자리에서 닿는 곳
        _, wcomp = cv2.connectedComponents(wall.astype(np.uint8), connectivity=8)
        for f in used:
            fill = (lab == f) & ~outside   # 벽 안에 갇힌 픽셀
            if f == s or fill.sum() < 8:
                continue
            ids = np.unique(wcomp[(cv2.dilate(fill.astype(np.uint8), square(1)) > 0) & wall])
            stroke = np.isin(wcomp, ids[ids > 0])   # 갇힌 픽셀을 감싼 벽
            if stroke.sum() < 8:
                continue
            fc, sc = med(fill), med(stroke)
            if min(dist2(fc, sc), dist2(fc, bg), dist2(sc, bg)) < 32 * 32 or color_between(fc, sc, bg) or color_between(sc, fc, bg) or snap_color(fc) == snap_color(sc):
                continue
            width = cv2.distanceTransform((~fill).astype(np.uint8), cv2.DIST_L2, 5)[stroke & (cv2.dilate(outside.astype(np.uint8), square(1)) > 0)]   # 벽 바깥쪽 끝에서 글자까지
            width = width[width > 0]
            if len(width) < 8 or np.median(width) < 2:
                continue
            score = dist2(fc, sc) * min(int((fill & ins).sum()), 4096)
            if best is None or score > best[0]:
                best = (score, hexc(fc), hexc(sc), float(np.median(width)), fill & ins if (fill & ins).sum() >= 50 else fill)
    if best:
        return best[1:]
    if len(used) == 1:
        return hexc(med(lab == used[0])), None, None, lab == used[0]
    def ink(k):
        m = lab == k
        n = int((m & ins).sum())
        return dist2(med(m), bg) * min(n + int(m.sum()) if n >= 8 else int(m.sum()), 4096)
    k = max([k for k in used if k != back], key=ink)
    m = (lab == k) & ins
    m = m if m.sum() >= 8 else lab == k
    return hexc(med(m)), None, None, m


#글자 상자 가운데 점이 들어간 말풍선 모양. bubbles: {말풍선 상자: 페이지 크기 모양}
def assign_bubbles(boxes, bubbles):
    def owner(box):
        cx, cy = (box[0] + box[2]) // 2, (box[1] + box[3]) // 2
        return next((b for b, m in bubbles.items() if m[cy, cx]), None)
    return [owner(b) for b in boxes]


def expand_RF(labels, bbox, box):
    x1, y1, x2, y2 = box
    for i in set(np.unique(labels[y1:y2, x1:x2])) - {0}:
        bx1, by1, bx2, by2 = bbox[i]
        x1, y1, x2, y2 = min(x1, bx1), min(y1, by1), max(x2, bx2), max(y2, by2)
    return (x1, y1, x2, y2)



#dmMaze/comic-text-detector 의 comictextdetector.pt 를 TorchScript 파일 하나로 옮긴 것 (글자 마스크·글자 줄을 내는 부분만. 모델 코드 없이 돈다)
#(11-25: onnxruntime 으로 돌리던 onnx 를 바꿈. onnx 는 1.16GB 를 잡고 놓지 않았다 → 토치 16비트는 0.3GB, 창고 비우기로 같이 비워진다. 29쪽 320개: 읽은 글자·색·굵기 전부 같음)
CTD_MODEL = os.environ.get("CTD_MODEL", "comictextdetector.jit.pt")
CTD_SIZE = 1024
BINARY_THRESHOLD = 60 / 255
CLOSE_RADIUS = 10
DILATE_RADIUS = 3

_ctd = None
def get_ctd():
    global _ctd
    if _ctd is None:
        import torch
        path = CTD_MODEL
        if not os.path.exists(path):
            path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), CTD_MODEL)
        cuda = torch.cuda.is_available()   # GPU 에서는 16비트(fp16)로 돌린다
        torch._C._jit_set_profiling_executor(False)   # LaMa 와 같은 설정 (inpaint.get_lama)
        torch._C._jit_set_profiling_mode(False)
        m = torch.jit.load(path, map_location="cuda" if cuda else "cpu").eval()
        _ctd = m.half() if cuda else m
    return _ctd


#상자 찾기·글자 읽기 모델(RF-DETR, CTD, HAYAI, SAM 2.1)을 그래픽카드에서 내린다. 다음에 쓸 때 저절로 다시 올라간다 (합쳐서 4초쯤)
#지우기를 시작할 때 그래픽카드 메모리가 모자라면 부른다 (inpaint.inpaint_lama)
def unload():
    global _rfdetr, _ctd
    import gc, torch
    from Process import hayai, sam_mask
    if _rfdetr is None and _ctd is None and hayai._model is None and sam_mask._model is None:
        return
    _rfdetr = _ctd = None
    with hayai._lock:
        hayai._model = hayai._processor = hayai._tokenizer = None
    sam_mask._model = sam_mask._processor = None   # sam_mask._cache (구해 둔 마스크)는 그대로 둔다: 효과음 렌더가 다시 쓴다
    gc.collect()
    torch.cuda.empty_cache()


def get_word_line_maps(image):
    import torch
    W, H = image.size
    s = CTD_SIZE / max(W, H)
    rw, rh = round(W * s), round(H * s)

    canvas = np.zeros((CTD_SIZE, CTD_SIZE, 3), np.uint8)
    canvas[:rh, :rw] = np.array(image.convert("RGB").resize((rw, rh)))
    inp = canvas.transpose(2, 0, 1)[None].astype(np.float32) / 255.0

    model = get_ctd()
    first = next(model.parameters())
    with torch.inference_mode():
        word, line = model(torch.from_numpy(inp).to(first.device, first.dtype))
    word, line = word[0, 0].float().cpu().numpy(), line[0, 0].float().cpu().numpy()
    up = lambda m: cv2.resize(m[:rh, :rw], (W, H), interpolation=cv2.INTER_LINEAR)
    return up(word), up(line)


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
#기울기는 줄의 아래 가장자리(밑선)로 잰다: 위에 붙은 후리가나에 안 끌리게
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
        cols = np.unique(xs)
        if len(cols) < 20:
            continue
        bottom = np.array([ys[xs == c].max() for c in cols], np.float32)
        step = max(1, len(cols) // 3)
        a = float(np.degrees(np.arctan(np.median((bottom[step:] - bottom[:-step]) / (cols[step:] - cols[:-step])))))
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
    t = int(np.median([thickness(l) for l in lines])) if lines else thickness(box)
    return g if t < g / 2 else t   # 줄 지도가 글자를 놓치고 점(…)만 잡으면 줄이 너무 가늘다 → 글자 덩어리 크기
