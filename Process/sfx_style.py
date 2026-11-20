#효과음 렌더: 색·굵기·테두리(대사와 같은 방식, detect_ocr.enclosed_colors)·회전·크기·늘이기는 원본에서 잰다(늘이기 = SAM 2.1 글자 마스크 직사각형의 한 글자 칸 세로/가로). 폰트는 설정에서 고른 것(없으면 Dokdo), 기울이기는 쓰지 않는다
import os, math, threading
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont
from Process.inpaint import decode

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_lock = threading.Lock()
_cache = {}


FONT, SMALL = "Dokdo", 0.9   # 설정에서 폰트가 안 오면 쓰는 폰트, 둘째 글자부터의 크기 비율
_SMALL_KANA = set("ッっャゃュゅョょァィゥェォぁぃぅぇぉヮゎ")
_NOT_LETTER = set("ー〜~…・.。、,!?！？♡♥❤☆★「」『』()（） \u3000-")


#늘이기 (11-20 결정): 글자 마스크를 감싸는 직사각형의 긴 변을 일본어 글자 수로 나눈 한 칸의 세로 ÷ 가로 (작은 글자 ッ·ュ 는 반 칸). 1.0~1.5
def stretch_of(rect, word):
    _, _, w, h, _ = rect
    n = max(1.0, sum(0.5 if ch in _SMALL_KANA else 1 for ch in (word or "") if ch not in _NOT_LETTER))
    r = (h / n) / w if h > w * 1.1 else h / (w / n)
    return float(np.clip(r, 1.0, 1.5))


def font_paths():
    if "fonts" not in _cache:
        from fonts.fonts import list_korean_fonts, FONTS_DIR
        _cache["fonts"] = {e["family"]: os.path.join(FONTS_DIR, e["regular"]) for e in list_korean_fonts()}
    return _cache["fonts"]


def font(path, size):
    k = (path, max(4, int(size)))
    if k not in _cache:
        _cache[k] = ImageFont.truetype(path, k[1])
    return _cache[k]


def stroke_width(mask):
    m = mask.astype(np.uint8)
    if m.sum() < 10:
        return 0.0
    d = cv2.distanceTransform(m, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)   # 정밀 거리 (3x3 근사는 값이 3.8·5.5·7.6 처럼 몇 단계로만 나온다)
    return float(4 * d[m > 0].mean())   # 획 폭 w 의 거리 평균은 w/4


SYMS = "♡♥!?"
def has_char(path, ch):
    k = ("cmap", path)
    if k not in _cache:
        from fontTools.ttLib import TTFont
        _cache[k] = set(TTFont(path, lazy=True).getBestCmap())
    return ord(ch) in _cache[k]


#번역문을 줄로 나눈다: 띄어쓰기가 있으면 그대로 줄, 없으면 영역 비율에 맞게 k 글자씩 (한 줄에 최대 6)
def split_lines(text, region, W, H):
    toks = []
    for t in text.replace("♥", "♡").split():
        t = "".join(ch for ch in t if "가" <= ch <= "힣" or ch in SYMS)
        if t and toks and not any("가" <= ch <= "힣" for ch in t):
            toks[-1] += t   # 따로 떨어진 ♡ 는 앞 줄 끝에 붙인다
        elif t:
            toks.append(t)
    if not toks:
        plain = [ch for ch in text if not ch.isspace()]
        return [plain] if plain else []
    if len(toks) > 1:
        return [list(t) for t in toks]
    chars = list(toks[0])
    n = len(chars)
    rw, rh = max(1, (region[2] - region[0]) * W), max(1, (region[3] - region[1]) * H)
    along, across = (rh, rw) if rh > rw * 1.1 else (rw, rh)
    best, best_k = -1, n
    for k in range(1, min(n, 6) + 1):
        cell = min(along / k, across / math.ceil(n / k))
        if cell > best:
            best, best_k = cell, k
    return [chars[i:i + best_k] for i in range(0, n, best_k)]


EM = 240            # 글자를 이 크기(폰트 px)로 그려 조립한 뒤 상자에 맞게 줄인다
SYM = 0.5           # ♡·!·? 크기
SHIFT = (0.0, 0.16)  # 첫 글자·나머지 글자를 옆으로 어긋나게 (EM 대비, 세로쓰기면 + 가 오른쪽)
GAP = 0.0           # 글자 사이 (EM 대비). 손 렌더와 비교해 0 이 가장 비슷
SYM_GAP = 0.08      # ♡ 앞은 띄운다 (붙으면 작게 줄였을 때 「아♡」가 「앙」처럼 보인다)
STRETCH = 1.0       # 상자를 채우려고 한쪽으로 늘리는 한도 (1 = 비율 유지. 11-12 손 렌더와 비교해 가장 비슷)
HALO = 0.6          # 그림 위 글자에 두르는 테두리 굵기 (원본 획 굵기 대비)
HEART_FONT = r"C:\Windows\Fonts\malgun.ttf"   # ♡ 는 폰트마다 모양이 달라서 하나로


def crop_ink(a):
    ys, xs = np.nonzero(a > 8)
    return a[ys.min():ys.max() + 1, xs.min():xs.max() + 1] if len(xs) else a


#글자 하나를 EM 크기로 그려 잉크만 잘라낸 L 그림
def glyph(path, ch):
    if ch in "♡♥" and os.path.exists(HEART_FONT):
        path = HEART_FONT
    elif not ("가" <= ch <= "힣") and not has_char(path, ch):   # 폰트에 없는 기호는 나눔고딕 것
        path = font_paths().get("NanumGothic", path)
    im = Image.new("L", (EM * 2, EM * 2), 0)
    ImageDraw.Draw(im).text((EM // 2, EM // 3), ch, font=font(path, EM), fill=255)
    return crop_ink(np.array(im))


def paste_max(dst, src, x, y):
    h, w = src.shape
    x0, y0, x1, y1 = max(0, x), max(0, y), min(dst.shape[1], x + w), min(dst.shape[0], y + h)
    if x1 > x0 and y1 > y0:
        np.maximum(dst[y0:y1, x0:x1], src[y0 - y:y1 - y, x0 - x:x1 - x], out=dst[y0:y1, x0:x1])


#글자 줄들을 한 덩어리(L)로. 세로쓰기는 첫 줄이 오른쪽. 길이는 (줄 방향, 옆 방향) 으로 다뤄 가로·세로를 같은 코드로
def text_block(path, lines, vertical, small):
    size = lambda a: a.shape if vertical else a.shape[::-1]
    empty = lambda along, across: np.zeros((along, across) if vertical else (across, along), np.uint8)
    put = lambda dst, src, along, across: paste_max(dst, src, across, along) if vertical else paste_max(dst, src, along, across)
    blocks = []
    for line in lines:
        cells = []
        for i, ch in enumerate(line):
            g, k = glyph(path, ch), SYM if ch in SYMS else 1.0 if i == 0 else small
            cells.append(cv2.resize(g, (max(1, int(g.shape[1] * k)), max(1, int(g.shape[0] * k))), interpolation=cv2.INTER_AREA))
        across = max(size(c)[1] for c in cells) + EM
        gaps = [0] + [(SYM_GAP if ch in SYMS else GAP) * EM for ch in line[1:]]
        a = empty(int(sum(size(c)[0] for c in cells) + sum(gaps)) + EM, across)
        pos = EM / 2
        for i, c in enumerate(cells):
            pos += gaps[i]
            off = SHIFT[min(i, 1)] * EM if len(cells) > 1 else 0
            put(a, c, int(pos), int((across - size(c)[1]) / 2 + off))
            pos += size(c)[0]
        blocks.append(crop_ink(a))
    if vertical:
        blocks = blocks[::-1]
    sep = int(EM * 0.15)
    out = empty(max(size(b)[0] for b in blocks), sum(size(b)[1] for b in blocks) + sep * (len(blocks) - 1))
    pos = 0
    for b in blocks:
        put(out, b, 0, pos)
        pos += size(b)[1] + sep
    return out


#늘이기(stretch: 세로/가로 비율, 1 보다 크면 길쭉하게), 기울이기(skew: 글자 모양을 비스듬히, 음수면 위가 오른쪽), 회전(줄 전체를 돌림, 반시계 +)
def shear_rotate(a, skew, rot, stretch=1.0):
    if abs(stretch - 1) > 0.01:
        r = math.sqrt(stretch)
        a = cv2.resize(a, (max(1, int(a.shape[1] / r)), max(1, int(a.shape[0] * r))), interpolation=cv2.INTER_LINEAR)
    a = np.pad(a, EM)
    h, w = a.shape
    if skew:
        a = cv2.warpAffine(a, np.float32([[1, skew, -skew * h / 2], [0, 1, 0]]), (w, h), flags=cv2.INTER_LINEAR)
    if abs(rot) > 0.5:
        a = np.array(Image.fromarray(a).rotate(rot, resample=Image.BICUBIC, expand=True))
    return crop_ink(a)


#상자에 맞게 줄이고, 남는 쪽은 STRETCH 배까지 늘려 채운다
def fit_region(a, rw, rh):
    h, w = a.shape
    s = min(rw / w, rh / h)
    sx, sy = min(rw / w, s * STRETCH), min(rh / h, s * STRETCH)
    return cv2.resize(a, (max(1, int(w * sx)), max(1, int(h * sy))), interpolation=cv2.INTER_AREA)


def grow(m, px):
    k = int(round(px))
    if k <= 0:
        return m
    return cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1, 2 * k + 1)))


def rgb(v):
    return tuple(int(np.clip(x, 0, 1) * 255) for x in v)


def lum(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


#st: font·skew·small·stretch·rotate·color·outline·outline_w·thick. region: 상자 안 글자 자리(0~1)
def render_box(bg, lines, st, region):
    H, W = bg.shape[:2]
    x1, y1, x2, y2 = region[0] * W, region[1] * H, region[2] * W, region[3] * H
    rw, rh = max(8, x2 - x1), max(8, y2 - y1)
    vertical = rh > rw * 1.1 and max(len(l) for l in lines) > 1
    m = text_block(font_paths()[st["font"]], lines, vertical, st["small"])
    m = shear_rotate(m, st["skew"], st["rotate"], st["stretch"])
    m = fit_region(m, rw, rh)
    thick = max(st["thick"], 1.0)
    cur = stroke_width(m > 127)   # 획 굵기를 원본에 맞춘다 (가는 획이 사라지지 않게 깎는 건 획의 1/4 까지)
    k = (thick - cur) / 2
    m = grow(m, k) if k >= 0.5 else cv2.erode(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * int(min(-k, cur / 4)) + 1,) * 2)) if k <= -0.5 else m
    color = rgb(st["color"])
    m = np.pad(m, int(thick * 2.5) + 4)   # 테두리를 키울 자리
    layers = []   # 바깥부터 (마스크, 색)
    out_c, ow = (rgb(st["outline"]), st["outline_w"] * thick) if st["outline"] is not None else (None, 0)
    if out_c is None:   # 테두리를 못 쟀는데 바탕이 그림이면(평평하지 않거나 글자색과 비슷하면) 반대색 테두리로 글자를 띄운다
        L = lum(bg[int(y1):int(y2), int(x1):int(x2)].reshape(-1, 3).astype(np.float32).T)
        if L.size and (L.std() > 25 or abs(L.mean() - lum(color)) < 90):
            out_c, ow = ((0, 0, 0) if lum(color) > 127 else (255, 255, 255)), max(3, thick * HALO)
    if out_c is not None and ow >= 1:
        layers.append((grow(m, ow), out_c))
    layers.append((m, color))
    out = Image.fromarray(bg).convert("RGB")
    px, py = int((x1 + x2) / 2 - m.shape[1] / 2), int((y1 + y2) / 2 - m.shape[0] / 2)
    for mask, c in layers:
        out.paste(c, (px, py), Image.fromarray(mask))
    return np.array(out)


#원본과 지운 그림이 다른 곳 = 지운 글자
def diff_mask(jp, bg):
    d = np.abs(np.asarray(jp).astype(np.int16) - np.asarray(bg).astype(np.int16)).sum(2) > 60
    d = cv2.morphologyEx(d.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return cv2.morphologyEx(d, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)) > 0


#효과음 색 (11-20 결정): 1. SAM 2.1 글자 마스크 → 2. 그 마스크를 감싸는 가장 작은 직사각형(cv2.minAreaRect) → 3. 직사각형을 바로 세워 그 안에서 색을 잰다
#색을 재는 방식은 대사와 같다(detect_ocr.enclosed_colors: 갇힌 색 = 글자색, 가둔 색 = 테두리색, 가둔 벽의 두께 = 테두리 굵기). 대사는 RF-DETR 상자에서 잰다
#page: 페이지(PIL, RGB), pos: 효과음 상자(탐지기 상자 또는 사람이 그린 상자). → (글자색, 테두리색 또는 None, 테두리 굵기 또는 None, 글자색으로 본 픽셀)
def sfx_colors(page, pos):
    from Process import sam_mask
    from Process.detect_ocr import enclosed_colors
    W, H = page.size
    #1. SAM 2.1 글자 마스크
    ar, k = sam_mask.letter_mask(page, pos)
    ys, xs = np.nonzero(k)
    if len(xs) < 3:   # 마스크가 비면 직사각형을 못 만든다 → 상자에서
        return enclosed_colors(np.asarray(page), pos, np.zeros((H, W), bool))
    #2. 최적의 직사각형
    (cx, cy), (w, h), a = cv2.minAreaRect(np.stack([xs + ar[0], ys + ar[1]], 1).astype(np.float32))
    #3. 직사각형을 바로 세워 그 안에서 색 (갇힌 색 후보 점수에 쓰는 글자 마스크는 SAM 2.1 둘째 후보)
    area, masks, _ = sam_mask.candidates(page, pos)
    glyphs = np.zeros((H, W), np.uint8)
    glyphs[area[1]:area[3], area[0]:area[2]] = masks[1]
    R = cv2.getRotationMatrix2D((cx, cy), a, 1.0)
    arr = cv2.warpAffine(np.asarray(page), R, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    glyphs = cv2.warpAffine(glyphs, R, (W, H), flags=cv2.INTER_NEAREST) > 0
    return enclosed_colors(arr, (int(cx - w / 2), int(cy - h / 2), int(math.ceil(cx + w / 2)), int(math.ceil(cy + h / 2))), glyphs)


#효과음 렌더용: 색·테두리(sfx_colors)와 획 굵기
def measure(page, pos):
    color, outline, width, fill = sfx_colors(page, pos)
    if fill.sum() < 50:
        return None
    thick = stroke_width(fill)
    unit = lambda h: [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return dict(tilt=0.0, area=int(fill.sum()), color=unit(color), outline=None if outline is None else unit(outline),
                outline_w=(width or 0) / max(thick, 1), thick=thick)


#글자 줄의 기울기(도). 세로축 기준, + 면 아래가 오른쪽. 덩어리가 길쭉하지 않으면(글자 하나 등) 방향이 없어 0
def tilt(d):
    ys, xs = np.nonzero(d)
    if len(xs) < 50:
        return 0.0
    val, vec = np.linalg.eigh(np.cov(np.stack([xs - xs.mean(), ys - ys.mean()])))
    if val[1] < 3.0 * max(val[0], 1e-6):   # 긴 축이 짧은 축의 √3 배 미만
        return 0.0
    vx, vy = vec[:, 1]
    if vy < 0:
        vx, vy = -vx, -vy
    a = math.degrees(math.atan2(vx, vy))
    if abs(a) > 45:   # 가로로 긴 줄: 가로축 기준 (+ 면 오른쪽 끝이 위)
        a = a - 90 if a > 0 else a + 90
    return float(np.clip(a, -30, 30))


#글자 마스크를 감싸는 가장 작은 직사각형(cv2.minAreaRect): (가운데 x, 가운데 y, 가로, 세로, 기울기)
#기울기 부호는 tilt 와 같다 (세로축 기준, + 면 아래가 오른쪽). 글자 하나짜리도 잴 수 있다. 깨끗한 글자 마스크(SAM 2.1)가 있을 때만 쓴다
def min_rect(mask):
    ys, xs = np.nonzero(mask)
    rect = cv2.minAreaRect(np.stack([xs, ys], 1).astype(np.float32))
    box = cv2.boxPoints(rect)
    e1, e2 = box[1] - box[0], box[2] - box[1]
    v, h = (e1, e2) if abs(e1[1]) > abs(e1[0]) else (e2, e1)   # 세로에 가까운 변, 가로에 가까운 변
    if v[1] < 0:
        v = -v
    return rect[0][0], rect[0][1], float(np.hypot(*h)), float(np.hypot(*v)), float(np.clip(math.degrees(math.atan2(v[0], v[1])), -30, 30))


#글자를 직사각형 가운데에 놓고, 돌린 채로 같은 배율로 키우다가 직사각형에 닿으면 멈춘다 → 그렇게 그려질 자리(0~1, W×H 조각 기준)
def rect_region(rect, lines, st, W, H):
    cx, cy, rw, rh, _ = rect
    vertical = rh > rw * 1.1 and max(len(l) for l in lines) > 1
    g = text_block(font_paths()[st["font"]], lines, vertical, st["small"])
    flat, turned = shear_rotate(g, st["skew"], 0, st["stretch"]), shear_rotate(g, st["skew"], st["rotate"], st["stretch"])
    k = min(rw / flat.shape[1], rh / flat.shape[0])   # 늘이기·기울이기까지 한 모양이 직사각형에 먼저 닿는 쪽
    bw, bh = turned.shape[1] * k, turned.shape[0] * k
    return (cx - bw / 2) / W, (cy - bh / 2) / H, (cx + bw / 2) / W, (cy + bh / 2) / H


#글씨체 → (폰트, 기울이기). 기울이기는 모델이 아직 안 내서 글씨체별 기본값 (음수면 위가 오른쪽으로 비스듬히).
#brush_hand 는 Nanum Brush Script 가 너무 가늘어서 East Sea Dokdo (11-12 33페이지 손 렌더 비교)
_SMALL = str.maketrans("ぁぃぅぇぉゃゅょゎ", "あいうえおやゆよわ")
_JSTRIP = set("っッーｰ〜~…・.。、,!?！？♡♥❤☆★「」『』()（） \u3000-")
def jnorm(t):
    import unicodedata
    out = []
    for ch in unicodedata.normalize("NFD", t or ""):
        if ch in ("\u3099", "\u309a") or ch in _JSTRIP:
            continue
        if "ァ" <= ch <= "ヶ":
            ch = chr(ord(ch) - 0x60)
        out.append(ch)
    return "".join(out).translate(_SMALL)


def text_mask(original, erased):
    o = np.asarray(original.convert("RGB")).astype(np.int16)
    e = np.asarray(erased.convert("RGB")).astype(np.int16)
    return np.abs(o - e).sum(2) > 60


def dedup(contents, textmask=None):
    def area(b):
        return max(1, b[2] - b[0]) * max(1, b[3] - b[1])

    def inter(a, b):
        return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))

    items = []
    for c in contents:
        x1, y1, x2, y2 = [int(v) for v in c["pos"]]
        t = float(textmask[max(0, y1):max(0, y2), max(0, x1):max(0, x2)].sum()) if textmask is not None else float(area(c["pos"]))
        items.append(dict(c, _n=jnorm(c.get("word")), _t=t, _d=t / area(c["pos"])))
    related = lambda x, y: (not x["_n"]) or (not y["_n"]) or x["_n"] in y["_n"] or y["_n"] in x["_n"]
    alive = list(range(len(items)))
    for i in sorted(alive, key=lambda i: -area(items[i]["pos"])):
        B = items[i]
        kids = [items[k] for k in alive if k != i and area(items[k]["pos"]) < area(B["pos"]) and inter(B["pos"], items[k]["pos"]) > 0.6 * area(items[k]["pos"])]
        other = sum(1 for C in kids if not related(B, C))
        if other >= 2 and other > len(kids) - other:
            alive.remove(i)
    changed = True
    while changed:
        changed = False
        for i in alive:
            for k in alive:
                A, C = items[i], items[k]
                if i == k or not A["_n"] or A["_n"] != C["_n"] or A["_t"] < C["_t"]:
                    continue
                if inter(A["pos"], C["pos"]) <= 0.4 * min(area(A["pos"]), area(C["pos"])):
                    continue
                alive.remove(k if A["_d"] >= 0.75 * C["_d"] else i)
                changed = True
                break
            if changed:
                break
    kept = []
    for i in sorted(alive, key=lambda i: (-len(items[i]["_n"]), -items[i]["_t"])):
        c = items[i]
        if any(inter(c["pos"], k["pos"]) > 0.4 * min(area(c["pos"]), area(k["pos"])) for k in kept):
            continue
        kept.append(c)
    return [{k: v for k, v in c.items() if k not in ("_n", "_t", "_d")} for c in kept]


def render_page(original, erased, contents):
    """original·erased: PIL 페이지. contents: [{pos, mask_area?, word, translated, group?, letter?, mask?, font?, small?, stretch?}]. 효과음만 지운 페이지 위에 그려서 돌려준다
    폰트는 상자에 있으면 그 폰트, 없으면 FONT. 늘이기는 글자 마스크로 잰다(마스크가 없으면 1.0). 기울이기는 쓰지 않는다 (11-20 결정)
    폰트·기울이기·둘째 글자부터 크기 small·늘이기 stretch 는 상자에 있으면 그 값, 없으면 모델(기울이기·늘이기)과 고정값(폰트·small). 획 굵기는 원본에 맞춘다, 없으면 모델이 고른 글씨체의 기본값. 이은 상자(group 이 같음)는 가장 크게 잰 상자의
    글씨체만 같이 쓰고 나머지는 상자마다 따로. 회전은 원본 글자 줄의 기울기 그대로 (기울이기는 글자 모양만 바꾸고 회전에는 안 쓴다). 글자 마스크가 있으면 회전·크기를 그걸 감싸는 가장 작은 직사각형으로: 그 기울기로 돌리고, 그 안에서 키우다 닿으면 멈춘다"""
    page = original.convert("RGB")
    src = np.array(page)
    out = np.array(erased.convert("RGB"))
    H, W = out.shape[:2]
    items = []
    with _lock:
        for c in dedup([c for c in contents if (c.get("translated") or "").strip()], text_mask(original, erased)):
            px1, py1, px2, py2 = [int(v) for v in c["pos"]]
            bx1, by1, bx2, by2 = [int(v) for v in (c.get("mask_area") or c["pos"])]
            bx1, by1, bx2, by2 = max(0, min(bx1, px1)), max(0, min(by1, py1)), min(W, max(bx2, px2)), min(H, max(by2, py2))
            if bx2 - bx1 < 8 or by2 - by1 < 8:
                continue
            cw, ch_ = bx2 - bx1, by2 - by1
            region = ((px1 - bx1) / cw, (py1 - by1) / ch_, (px2 - bx1) / cw, (py2 - by1) / ch_)
            lines = split_lines(c["translated"], region, cw, ch_)
            if not sum(len(l) for l in lines):
                continue
            jp = src[by1:by2, bx1:bx2]
            letter = None
            if c.get("letter") and c.get("mask") and c.get("mask_area"):   # 사람이 그린 효과음 상자: SAM 2.1 글자 마스크로 잰다 (mask 는 mask_area 크기)
                ax1, ay1 = int(c["mask_area"][0]), int(c["mask_area"][1])
                k = decode(c["mask"])
                letter = np.zeros(jp.shape[:2], bool)
                letter[ay1 - by1:ay1 - by1 + k.shape[0], ax1 - bx1:ax1 - bx1 + k.shape[1]] = k
                if letter.sum() < 50:
                    letter = None
            m = measure(page, (max(0, px1), max(0, py1), min(W, px2), min(H, py2)))   # 효과음: SAM 2.1 마스크 → 직사각형 → 직사각형에서 색 (sfx_colors)
            if m is None:
                continue
            #기울기는 글자 상자(pos) 안의 지운 어두운 잉크로 잰다 (지운 영역 mask_area 는 넓어서 옆 그림 선까지 걸리고, 흰 테두리는 방향을 흐린다)
            pj = src[max(0, py1):py2, max(0, px1):px2]
            rect = None if letter is None else min_rect(letter)   # 글자 마스크가 있으면 회전·크기를 그걸 감싸는 직사각형으로 정한다
            m["tilt"] = tilt(diff_mask(pj, out[max(0, py1):py2, max(0, px1):px2]) & (pj.mean(2) < 100)) if rect is None else rect[4]
            items.append(dict(box=(bx1, by1, bx2, by2), region=region, lines=lines, m=m, c=c, group=c.get("group"), rect=rect, pos=(max(0, px1), max(0, py1), min(W, px2), min(H, py2))))
        for it in items:   # 상자에 값이 있으면 그 값
            c = it["c"]
            it["font"] = c["font"] if c.get("font") in font_paths() else FONT
            it["skew"], it["small"] = 0.0, float(c.get("small", SMALL))
            it["stretch"] = float(c["stretch"]) if "stretch" in c else stretch_of(it["rect"], c.get("word")) if it["rect"] else 1.0
        groups = {}
        for it in items:
            if it["group"] is not None:
                groups.setdefault(it["group"], []).append(it)
        for g in groups.values():   # 이은 상자는 글씨체만 같게 (가장 크게 잰 상자 것). 나머지는 다른 글자 줄처럼 상자마다 따로
            lead = max(g, key=lambda it: it["m"]["area"])
            for it in g:
                it["font"] = lead["font"]
        for it in items:
            m = it["m"]
            st = dict(font=it["font"], skew=it["skew"], small=it["small"], stretch=it["stretch"], rotate=m["tilt"], color=m["color"], outline=m["outline"],
                      outline_w=m["outline_w"], thick=m["thick"])
            bx1, by1, bx2, by2 = it["box"]
            region = rect_region(it["rect"], it["lines"], st, bx2 - bx1, by2 - by1) if it["rect"] else it["region"]
            out[by1:by2, bx1:bx2] = render_box(out[by1:by2, bx1:bx2], it["lines"], st, region)
    return Image.fromarray(out)
