#효과음 렌더: 색·굵기는 원본에서 재고, 글씨체·초성 배율·글자 크기는 models/sfx_ar.pt 가 정한다
import os, math, threading
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG = 224
CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
JONG = ["", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ", "ㄻ", "ㄼ", "ㄽ", "ㄾ", "ㄿ", "ㅀ", "ㅁ", "ㅂ", "ㅄ", "ㅅ", "ㅆ", "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ"]
VERT_V = set("ㅏㅐㅑㅒㅓㅔㅕㅖㅣ")
HORI_V = set("ㅗㅛㅜㅠㅡ")
_lock = threading.Lock()
_cache = {}


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
    d = cv2.distanceTransform(m, cv2.DIST_L2, 3)
    return float(4 * np.median(d[m > 0]))


#글자(또는 자모)를 box_w×box_h 안에 비율 유지해 꽉 차게 그린 L 그림(여백 없음). 실제 잉크 영역 기준
def glyph(path, text, box_w, box_h, stroke=0):
    size = int(max(box_w, box_h) * 1.3) + 4
    f = font(path, size)
    bb = f.getbbox(text)
    sw = int(round(stroke * 1.3))
    pad = sw + size // 2 + 4
    im = Image.new("L", (max(1, bb[2] - bb[0]) + 2 * pad, max(1, bb[3] - bb[1]) + 2 * pad), 0)
    ImageDraw.Draw(im).text((pad - bb[0], pad - bb[1]), text, font=f, fill=255, stroke_width=sw, stroke_fill=255)
    ink = im.getbbox()
    if ink is None:
        return Image.new("L", (max(1, int(box_w)), max(1, int(box_h))), 0)
    im = im.crop(ink)
    sc = min(box_w / im.width, box_h / im.height)
    return im.resize((max(1, int(im.width * sc)), max(1, int(im.height * sc))), Image.BILINEAR)


def paste_fit(canvas, im, box):
    x1, y1, x2, y2 = [int(v) for v in box]
    bw, bh = max(1, x2 - x1), max(1, y2 - y1)
    s = min(bw / im.width, bh / im.height)
    im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.BILINEAR)
    canvas.paste(im, (x1 + (bw - im.width) // 2, y1 + (bh - im.height) // 2), im)


def fit_canvas(im, w, h):
    canvas = Image.new("L", (w, h), 0)
    paste_fit(canvas, im, (0, 0, w, h))
    return canvas


#칸을 채우게 가로·세로를 따로 늘린다. 한쪽만 STRETCH 배까지 (한글판 효과음도 글자를 길쭉하게 늘려 칸을 채운다)
STRETCH = 1.4
def fill_canvas(im, w, h):
    s = min(w / im.width, h / im.height)
    sx, sy = min(w / im.width, s * STRETCH), min(h / im.height, s * STRETCH)
    im = im.resize((max(1, int(im.width * sx)), max(1, int(im.height * sy))), Image.BILINEAR)
    canvas = Image.new("L", (w, h), 0)
    canvas.paste(im, ((w - im.width) // 2, (h - im.height) // 2))
    return canvas


SYMS = "♡♥!?"
def has_char(path, ch):
    k = ("cmap", path)
    if k not in _cache:
        from fontTools.ttLib import TTFont
        _cache[k] = set(TTFont(path, lazy=True).getBestCmap())
    return ord(ch) in _cache[k]


#한 글자를 w×h L 그림으로. 초성 배율이 1 과 다르면 자모를 정사각형 칸에서 따로 그려 조립한다
def char_mask(path, ch, w, h, cho_scale):
    w, h = max(8, int(w)), max(8, int(h))
    if not ("가" <= ch <= "힣"):
        if not has_char(path, ch):   # ♡ 가 없는 폰트는 나눔고딕 것을 쓴다 (굵기는 뒤에서 맞춘다)
            path = font_paths().get("NanumGothic", path)
        return fit_canvas(glyph(path, ch, w, h), w, h)
    code = ord(ch) - 0xAC00
    cho, jung, jong = CHO[code // 588], JUNG[(code % 588) // 28], JONG[code % 28]
    if abs(cho_scale - 1) < 0.15 or (jung not in VERT_V and jung not in HORI_V):
        return fill_canvas(glyph(path, ch, w, h), w, h)
    S = max(w, h)
    canvas = Image.new("L", (S, S), 0)
    cs = min(cho_scale, 2.5)
    if jung in VERT_V:      # 초성 왼쪽, 중성 오른쪽, 종성 아래
        ch_h = S * (0.62 if jong else 1.0)
        cho_w, cho_h = min(S * 0.48 * cs, S * 0.78), min(ch_h * 0.62 * cs, S * (0.68 if jong else 0.9))
        paste_fit(canvas, glyph(path, cho, cho_w, cho_h), (0, 0, cho_w, cho_h))
        jx = S * 0.56
        paste_fit(canvas, glyph(path, jung, max(8, S - jx), ch_h), (jx, 0, S, ch_h))
        if jong:
            paste_fit(canvas, glyph(path, jong, S * 0.8, S - ch_h - S * 0.03), (S * 0.1, ch_h + S * 0.03, S * 0.9, S))
    else:                   # 초성 위, 중성 가운데, 종성 아래
        top = S * (0.38 if jong else 0.5)
        cho_w, cho_h = min(S * 0.5 * cs, S * 0.95), min(top * 0.75 * cs, S * (0.48 if jong else 0.6))
        paste_fit(canvas, glyph(path, cho, cho_w, cho_h), ((S - cho_w) / 2, 0, (S + cho_w) / 2, cho_h))
        mid_h = (S * 0.68 if jong else S) - cho_h
        paste_fit(canvas, glyph(path, jung, S, max(8, mid_h)), (0, cho_h, S, cho_h + mid_h))
        if jong:
            paste_fit(canvas, glyph(path, jong, S * 0.8, S * 0.3), (S * 0.1, S * 0.7, S * 0.9, S))
    ink = canvas.getbbox()
    return fill_canvas(canvas.crop(ink) if ink else canvas, w, h)


#획 굵기 맞추기: 목표보다 가늘면 두껍게, 굵으면 깎는다
#획 굵기 맞추기. 가는 획이 사라지거나 구멍이 메워지지 않게 깎고 붙이는 양을 제한한다
def match_thickness(mask_im, target_px):
    m = np.array(mask_im) > 127
    if m.sum() < 10:
        return mask_im
    cur = stroke_width(m)
    k = int(round(abs(target_px - cur) / 2))
    if target_px < cur:
        d = cv2.distanceTransform(m.astype(np.uint8), cv2.DIST_L2, 3)
        ridge = m & (d >= cv2.dilate(d, np.ones((3, 3), np.uint8)) - 1e-3) & (d >= 1)
        thin = float(2 * np.percentile(d[ridge], 20)) if ridge.sum() > 10 else cur
        k = min(k, int(0.25 * thin))
    else:
        k = min(k, max(1, int(cur)))   # 가는 폰트도 원본 굵기까지 (최대 3배)
    if k < 1:
        return mask_im
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1, 2 * k + 1))
    a = (m * 255).astype(np.uint8)
    return Image.fromarray(cv2.dilate(a, ker) if target_px > cur else cv2.erode(a, ker))


#lines: 글자 줄 목록. 글자별 상대 크기(size)는 모델 예측 (줄 안에서 비율로만 쓴다)
def layout_lines(lines, chars_st, region, W, H):
    x1, y1, x2, y2 = region[0] * W, region[1] * H, region[2] * W, region[3] * H
    rw, rh = max(8, x2 - x1), max(8, y2 - y1)
    vertical = rh > rw * 1.1 and max(len(l) for l in lines) > 1
    L, k = len(lines), max(len(l) for l in lines)
    along, across = (rh, rw) if vertical else (rw, rh)   # 줄 방향 길이, 줄 쌓는 방향 길이
    cell = min(along / k, across / L)
    line_gap = across / L
    out, idx = [], 0
    for li, line in enumerate(lines):
        st = chars_st[idx:idx + len(line)]
        sizes = np.array([float(np.clip(c.get("size", 1.0), 0.6, 1.6)) for c in st] + [1.0] * (len(line) - len(st)))
        sizes = np.where([ch in SYMS for ch in line], 0.6, sizes)   # ♡·! 는 글자보다 작게
        sizes = sizes / sizes.sum() * min(along, cell * len(line) * STRETCH)
        pos = (along - sizes.sum()) / 2
        off = (L - 1 - li if vertical else li) * line_gap + line_gap / 2   # 세로쓰기는 오른쪽 줄이 첫 줄
        for ci, ch in enumerate(line):
            c = dict(st[ci]) if ci < len(st) else dict(size=1.0, cho=1.0, angle=0.0)
            s_ = sizes[ci]
            w_, h_ = (min(line_gap, s_ * 1.1), s_ * 0.92) if vertical else (s_ * 0.92, min(line_gap, s_ * 1.1))
            cx = (x1 + off) if vertical else (x1 + pos + s_ / 2)
            cy = (y1 + pos + s_ / 2) if vertical else (y1 + off)
            out.append(dict(c, ch=ch, cx=cx / W, cy=cy / H, w=w_ / W, h=h_ / H))
            pos += s_
        idx += len(line)
    return out


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


def render_crop(bg, lines, st, region):
    H, W = bg.shape[:2]
    lay = layout_lines(lines, st["chars"], region, W, H)
    chars = [c["ch"] for c in lay]
    path = font_paths()[st["font"]]
    color = tuple(int(np.clip(v, 0, 1) * 255) for v in st["color"])
    out_c = None if st["outline"] is None else tuple(int(np.clip(v, 0, 1) * 255) for v in st["outline"])
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for ch, c in zip(chars, lay):
        cw, chh = max(8, c["w"] * W), max(8, c["h"] * H)
        thick = st["thick_px"]
        ow = int(round(st["outline_w"] * max(thick, 1))) if out_c else 0
        fill = match_thickness(char_mask(path, ch, cw, chh, c.get("cho", 1.0)), thick)
        tile = Image.new("RGBA", fill.size, (0, 0, 0, 0))
        oc = out_c
        tx, ty = int(c["cx"] * W - fill.width / 2), int(c["cy"] * H - fill.height / 2)
        under = bg[max(0, ty):max(0, ty) + fill.height, max(0, tx):max(0, tx) + fill.width]
        fm = (np.array(fill) > 127)[:under.shape[0], :under.shape[1]]
        if fm.sum() > 20:
            lum = lambda rgb: 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
            bl = lum(under[fm].astype(np.float32))
            fl = float(lum(np.array(color, np.float32)))
            hidden = np.abs(bl - fl) < 60
            if oc is not None:
                hidden &= np.abs(bl - float(lum(np.array(oc, np.float32)))) < 60
            if hidden.mean() > 0.3:
                oc = (0, 0, 0) if fl > 127 else (255, 255, 255)
                ow = max(ow, 2, int(round(thick * 0.3)))
        out_c_ = oc
        if ow > 0 and out_c_ is not None:
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * ow + 1, 2 * ow + 1))
            tile.paste(Image.new("RGBA", fill.size, out_c_ + (255,)), (0, 0), Image.fromarray(cv2.dilate(np.array(fill), k)))
        tile.paste(Image.new("RGBA", fill.size, color + (255,)), (0, 0), fill)
        if abs(st.get("shear", 0)) >= 5:
            k = math.tan(math.radians(st["shear"]))
            M = np.float32([[1, k, -k * tile.height / 2 + abs(k) * tile.height / 2], [0, 1, 0]])
            tile = Image.fromarray(cv2.warpAffine(np.array(tile), M, (int(tile.width + abs(k) * tile.height), tile.height), flags=cv2.INTER_LINEAR, borderValue=(0, 0, 0, 0)))
        if abs(c.get("angle", 0)) > 3:
            tile = tile.rotate(c["angle"], expand=True, resample=Image.BILINEAR)
        layer.alpha_composite(tile, (int(c["cx"] * W - tile.width / 2), int(c["cy"] * H - tile.height / 2)))
    out = Image.fromarray(bg).convert("RGBA")
    out.alpha_composite(layer)
    return np.array(out.convert("RGB"))


def measure(jp, bg):
    jp = np.asarray(jp)
    d = np.abs(jp.astype(np.int16) - bg.astype(np.int16)).sum(2) > 60
    d = cv2.morphologyEx(d.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    d = cv2.morphologyEx(d, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)) > 0
    if d.sum() < 100:
        return None
    region = cv2.dilate(d.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    px = jp[region].astype(np.float32)
    K = 3
    _, lab, cen = cv2.kmeans(px, K, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0), 3, cv2.KMEANS_PP_CENTERS)
    labimg = np.full(d.shape, -1, np.int32)
    labimg[region] = lab.ravel()
    inside = [((labimg == c) & d).sum() / max(((labimg == c) & region).sum(), 1) for c in range(K)]
    bg_c = int(np.argmin(inside))
    dd = cv2.distanceTransform(d.astype(np.uint8), cv2.DIST_L2, 3)
    cand = [c for c in range(K) if c != bg_c]
    depth = [dd[(labimg == c) & d].mean() if ((labimg == c) & d).sum() > 20 else -1 for c in cand]
    fill_c = cand[int(np.argmax(depth))]
    other = cand[1 - int(np.argmax(depth))]
    fill = (labimg == fill_c) & region
    fill = cv2.morphologyEx(fill.astype(np.uint8), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8)) > 0
    n_, lab_, _, _ = cv2.connectedComponentsWithStats(fill.astype(np.uint8), 8)
    if n_ > 1:   # 차이 마스크에 걸친 덩어리만 글자
        keep = np.concatenate([[False], np.bincount(lab_[d], minlength=n_)[1:] > 0])
        if keep.any():
            fill = keep[lab_]
    if fill.sum() < 50:
        return None
    thick = stroke_width(fill)
    ring = (cv2.dilate(fill.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0) & ~fill & (labimg != fill_c) & region
    outline, ow = None, 0
    if ring.sum() > 20 and (labimg[ring] == other).mean() > 0.5 and inside[other] > 0.5:
        outline = cen[other]
        cur = fill.astype(np.uint8)
        top = max(2, int(thick * 0.6))
        for w in range(1, top + 1):
            nxt = cv2.dilate(cur, np.ones((3, 3), np.uint8))
            band = (nxt > 0) & (cur == 0) & (labimg != fill_c)
            if band.sum() < 10 or (labimg[band] == other).mean() < 0.45:
                break
            ow, cur = w, nxt
        #"테두리"가 글자 획만큼 두꺼우면 어느 쪽이 글자인지 애매하다 → 어두운 쪽을 글자로 (흰 테두리 두른 검은 글씨가 흰 글씨로 뒤집혀 잡히던 것)
        if ow == top and cen[other].mean() < cen[fill_c].mean():
            fill_c, other = other, fill_c
            outline, ow = cen[other], 0.4 * thick
    return dict(color=[float(v) / 255 for v in cen[fill_c]], outline=None if outline is None else [float(v) / 255 for v in outline],
                outline_w=ow / max(thick, 1), thick=thick)


#  글씨체 → 폰트·흔들림은 아래 STYLE_FONT 표. 색·테두리·굵기는 measure() 가 조각에서 잰다
STYLE_FONT = {
    "marker_hand": ("Dokdo", 2), "pen_hand": ("Nanum Pen", 2), "brush_font": ("East Sea Dokdo", 0), "brush_slant": ("Kirang Haerang", 0),
    "marker_font": ("Jua", 0), "brush_hand": ("Nanum Brush Script", 2), "round_hand": ("Gaegu", 1), "bold_hand": ("Black Han Sans", 1), "gothic_font": ("NanumGothic", 0),
}
MODEL_PATH = os.environ.get("SFX_STYLE_MODEL") or os.path.join(ROOT, "models", "sfx_ar.pt")


def _net():
    if "net" not in _cache:
        import torch, torch.nn as nn, torchvision
        ck = torch.load(MODEL_PATH, map_location="cpu", weights_only=False)
        STYLES, CK, MAXC = ck["styles"], ck["char_keys"], ck["maxc"]

        class Net(nn.Module):
            def __init__(self, d=256):
                super().__init__()
                bb = torchvision.models.resnet18(weights=None)
                bb.fc = nn.Identity()
                self.bb = bb
                self.ctx = nn.Sequential(nn.Linear(512 + 1, d), nn.ReLU())
                self.style = nn.Linear(d, len(STYLES))
                self.style_emb = nn.Embedding(len(STYLES), d)
                self.char_emb = nn.Embedding(11173, d)
                self.prev_proj = nn.Linear(len(CK), d)
                self.pos = nn.Parameter(torch.zeros(MAXC, d))
                layer = nn.TransformerEncoderLayer(d, 4, d * 2, dropout=0.1, batch_first=True)
                self.dec = nn.TransformerEncoder(layer, 3)
                self.head = nn.Linear(d, len(CK))
                self.start = nn.Parameter(torch.zeros(len(CK)))

            def decode(self, ctx, sid, ids, prev):
                tok = self.char_emb(ids) + self.prev_proj(prev) + self.pos[None] + ctx[:, None] + self.style_emb(sid)[:, None]
                mask = torch.triu(torch.ones(MAXC, MAXC, device=ids.device, dtype=torch.bool), 1)
                return self.head(self.dec(tok, mask=mask))

            @torch.no_grad()
            def generate(self, x, asp, ids, n):
                ctx = self.ctx(torch.cat([self.bb(x), asp], 1))
                sid = self.style(ctx).argmax(1)
                prev = self.start[None, None].expand(len(ids), MAXC, -1).clone()
                out = torch.zeros(len(ids), MAXC, len(CK))
                for k in range(n):
                    o = self.decode(ctx, sid, ids, prev)[:, k]
                    out[:, k] = o
                    if k + 1 < MAXC:
                        prev[:, k + 1] = o
                return sid, out

        net = Net().eval()
        net.load_state_dict(ck["state"])
        _cache["net"] = (net, STYLES, CK, MAXC)
    return _cache["net"]


def predict(jp_im, chars):
    """jp_im: PIL 일본어 조각, chars: 한글 글자 목록 → (style, [{size, angle, cho, dx, dy}])"""
    import torch
    net, STYLES, CK, MAXC = _net()
    w, h = jp_im.size
    s = IMG / max(w, h)
    im = jp_im.resize((max(1, round(w * s)), max(1, round(h * s))), Image.BILINEAR)
    canvas = Image.new("RGB", (IMG, IMG), (128, 128, 128))
    canvas.paste(im, ((IMG - im.width) // 2, (IMG - im.height) // 2))
    x = (torch.from_numpy(np.asarray(canvas).astype(np.float32) / 255).permute(2, 0, 1) - 0.5) / 0.5
    ids = torch.zeros(1, MAXC, dtype=torch.long)
    n = min(len(chars), MAXC)
    for k, ch in enumerate(chars[:n]):
        ids[0, k] = ord(ch) - 0xAC00 + 1 if "가" <= ch <= "힣" else 0
    sid, out = net.generate(x[None], torch.tensor([[math.log(w / h)]], dtype=torch.float32), ids, n)
    rows = [dict(zip(CK, r)) for r in out[0, :n].tolist()]
    res = []
    for ch, r in zip(chars[:n], rows):
        cho = float(np.clip(r["cho"], 0.9, 2.0))
        if not ("가" <= ch <= "힣") or CHO[(ord(ch) - 0xAC00) // 588] not in "ㅇㅎㄱㅈㅊㅋ":   # 과장은 둥근·열린 초성에만 (라벨 규칙과 같게)
            cho = 1.0
        res.append(dict(size=float(np.clip(r["size"], 0.5, 2.0)), angle=float(np.clip(r["angle"] * 45, -30, 30)), cho=cho))
    return STYLES[int(sid[0])], res


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
    """original·erased: PIL 페이지. contents: [{pos, mask_area?, translated, font?}]. 효과음만 지운 페이지 위에 그려서 돌려준다
    폰트는 페이지에 하나: 한 페이지의 효과음은 한 사람이 같은 펜으로 쓴 것이라, 전체 굵기 중앙값으로 하나를 정한다
    (상자마다 고르면 작은 상자는 굵은 폰트, 큰 상자는 얇은 폰트로 갈려서 제각각이 된다). 색·테두리·굵기는 상자마다 잰 대로. 상자에 font 가 지정돼 있으면 그걸 쓴다"""
    src = np.array(original.convert("RGB"))
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
            n = sum(len(l) for l in lines)
            if not n:
                continue
            jp = src[by1:by2, bx1:bx2]
            m = measure(jp, out[by1:by2, bx1:bx2])
            if m is None:
                continue
            flat = [ch for line in lines for ch in line]
            style, pred = predict(Image.fromarray(jp), flat)
            st = dict(color=m["color"], outline=m["outline"], outline_w=m["outline_w"], thick_px=m["thick"], shear=0.0, chars=pred)
            items.append(dict(box=(bx1, by1, bx2, by2), region=region, lines=lines, st=st, style=style, font=c.get("font")))
        #페이지 폰트 하나: 글씨체 다수결 (한 페이지 효과음은 같은 펜). 상자에 font 가 지정돼 있으면 그걸 쓴다
        if items:
            from collections import Counter
            page_style = Counter(it["style"] for it in items).most_common(1)[0][0]
            page_font = STYLE_FONT[page_style][0]
            if page_font not in font_paths():
                page_font = "Dokdo"
            for it in items:
                it["st"]["font"] = it["font"] if it["font"] in font_paths() else page_font
                bx1, by1, bx2, by2 = it["box"]
                out[by1:by2, bx1:bx2] = render_crop(out[by1:by2, bx1:bx2], it["lines"], it["st"], it["region"])
    return Image.fromarray(out)
