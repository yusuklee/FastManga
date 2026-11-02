import base64, io
import numpy as np
import cv2
from PIL import Image


def square(r):
    return np.ones((2 * r + 1, 2 * r + 1), np.uint8)


TILE = 512      # 한 번에 지울 조각의 최대 한 변
CTX = 128       # 조각 사방에 붙여 모델에 보여줄 배경
FONT_RATIO = 0.16         # koharu 0.61.2 LEGACY_BLOCK_DILATE_FONT_RATIO
MIN_R, MAX_R = 2, 8       # LEGACY_MIN/MAX_DILATE_RADIUS
MIN_PIXELS = 16
margin1 = 4     # 상자에서 이만큼 밖까지는 글자 번짐이라 버린다
margin2 = 3     # 그 바깥으로 이만큼이 색을 잴 고리


def box_masks(image, contents):
    W, H = image.size
    out = []
    for c in contents:
        x1, y1, x2, y2 = map(int, c.get("mask_area") or c["pos"])
        r = int(np.clip(round(min(x2 - x1, y2 - y1) * FONT_RATIO), MIN_R, MAX_R))
        ex1, ey1, ex2, ey2 = max(0, x1 - r), max(0, y1 - r), min(W, x2 + r), min(H, y2 + r)
        page = np.zeros((H, W), np.uint8)
        page[y1:y2, x1:x2] = np.array(Image.open(io.BytesIO(base64.b64decode(c["mask"])))) > 127 if c.get("mask") else 1
        out.append(((ex1, ey1, ex2, ey2), cv2.dilate(page[ey1:ey2, ex1:ex2], square(r)) > 0))
    return out


def uniform_color(arr, box, text_mask):
    x1, y1, x2, y2 = box
    sel = np.zeros(arr.shape[:2], bool)
    sel[max(y1 - margin1, 0):y2 + margin1, max(x1 - margin1, 0):x2 + margin1] = True
    sel[max(y1 - margin2, 0):y2 + margin2, max(x1 - margin2, 0):x2 + margin2] = False
    sel[y1:y2, x1:x2] = ~text_mask
    px = arr[sel]
    if len(px) < MIN_PIXELS:
        return None
    devs = px.std(0)
    if devs.max() >= (7.0 if devs.std() > 1.0 else 10.0):
        return None
    return np.median(px, 0).astype(np.uint8)


def merge_boxes(boxes, gap=CTX):
    for i, a in enumerate(boxes):
        for j in range(i + 1, len(boxes)):
            b = boxes[j]
            if b[0] <= a[2] + gap and a[0] - gap <= b[2] and b[1] <= a[3] + gap and a[1] - gap <= b[3]:
                boxes[i] = (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))
                boxes.pop(j)
                return merge_boxes(boxes, gap)
    return boxes


_lama = None
def get_lama():
    global _lama
    if _lama is None:
        import os, torch
        path = os.environ.get("LAMA_MODEL") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "anime-manga-big-lama.pt")
        dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        torch._C._jit_set_profiling_executor(False)   # 켜 두면 새 입력 크기마다 다시 최적화해서 조각마다 수 초씩 걸린다
        torch._C._jit_set_profiling_mode(False)
        with open(path, "rb") as f:
            _lama = torch.jit.load(f, map_location=dev).eval().to(dev)
    return _lama


#같은 크기의 조각 여러 개를 한 번에 지운다. crops: HxWx3 uint8, masks: HxW bool
def call_lama(crops, masks):
    import torch
    model = get_lama()
    dev = next(model.parameters()).device
    H, W = crops[0].shape[:2]
    ph, pw = (8 - H % 8) % 8, (8 - W % 8) % 8
    x = torch.from_numpy(np.stack([np.pad(c, ((0, ph), (0, pw), (0, 0)), mode="reflect") for c in crops])).to(dev).permute(0, 3, 1, 2).float() / 255
    m = torch.from_numpy(np.stack([np.pad(k, ((0, ph), (0, pw)), mode="reflect") for k in masks])).to(dev)[:, None].float()
    with torch.inference_mode():
        y = model(x, m)
    return list((y[:, :, :H, :W].permute(0, 2, 3, 1).clamp(0, 1) * 255).round().byte().cpu().numpy())


BUCKET = 64     # 조각 크기를 이 단위로 올림해서 같은 크기끼리 묶는다
MAX_BATCH = 8


def inpaint_lama(image, contents, tile=TILE):
    arr = np.array(image.convert("RGB"))
    h, w = arr.shape[:2]
    page_mask = np.zeros((h, w), bool)
    boxes = []
    for (x1, y1, x2, y2), m in box_masks(image, contents):
        color = uniform_color(arr, (x1, y1, x2, y2), m)
        if color is not None:
            arr[y1:y2, x1:x2][m] = color
        else:
            page_mask[y1:y2, x1:x2] |= m
            boxes.append((x1, y1, x2, y2))
    groups = {}
    for bx1, by1, bx2, by2 in merge_boxes(boxes):
        for y1 in range(by1, by2, tile):
            for x1 in range(bx1, bx2, tile):
                x2, y2 = min(x1 + tile, bx2), min(y1 + tile, by2)
                cx1, cy1, cx2, cy2 = max(0, x1 - CTX), max(0, y1 - CTX), min(w, x2 + CTX), min(h, y2 + CTX)
                key = (-(-(cy2 - cy1) // BUCKET) * BUCKET, -(-(cx2 - cx1) // BUCKET) * BUCKET)
                groups.setdefault(key, []).append((x1, y1, x2, y2, cx1, cy1, cx2, cy2))
    for (BH, BW), jobs in groups.items():
        for i in range(0, len(jobs), MAX_BATCH):
            chunk = jobs[i:i + MAX_BATCH]
            crops, masks = [], []
            for x1, y1, x2, y2, cx1, cy1, cx2, cy2 in chunk:
                crop, mk = arr[cy1:cy2, cx1:cx2], page_mask[cy1:cy2, cx1:cx2]
                ch, cw = crop.shape[:2]
                crops.append(np.pad(crop, ((0, BH - ch), (0, BW - cw), (0, 0)), mode="reflect"))
                masks.append(np.pad(mk, ((0, BH - ch), (0, BW - cw)), mode="reflect"))
            for (x1, y1, x2, y2, cx1, cy1, cx2, cy2), out in zip(chunk, call_lama(crops, masks)):
                m = page_mask[y1:y2, x1:x2]
                arr[y1:y2, x1:x2][m] = out[y1 - cy1:y2 - cy1, x1 - cx1:x2 - cx1][m]
    return Image.fromarray(arr)
