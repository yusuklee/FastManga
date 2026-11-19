#효과음 스타일 모델: 일본어 효과음 조각 → 기울이기·늘이기 (3단계씩). 폰트와 첫 글자 크기 비율은 고정값
#SigLIP 2 그림 인코더 + 한 쪽의 효과음끼리 서로 보는 트랜스포머 2층 + 머리 2개. 학습: D:\sfx_train\label4\finetune2.py (japanese 8편, 라벨 5,061개)
import os, threading

REPO, REV = "yusuklee/fastmanga-sfx-style", "e1b72581b06e4af75763f4476e56dcd3eb907d8e"
PATTERNS = ["*.json", "*.safetensors"]
FONT, SMALL = "Dokdo", 0.9   # 모델이 정하지 않는 값: 폰트, 둘째 글자부터의 크기 비율 (라벨에서 가장 흔한 값)

_net = None
_lock = threading.Lock()


def load():
    global _net
    with _lock:
        if _net is None:
            import json
            import torch, torch.nn as nn
            from huggingface_hub import snapshot_download
            from safetensors.torch import load_file
            from transformers import SiglipVisionConfig, SiglipVisionModel
            path = snapshot_download(REPO, revision=REV, allow_patterns=PATTERNS)
            cfg = json.load(open(os.path.join(path, "config.json"), encoding="utf-8"))
            d = cfg["d"]

            class Net(nn.Module):
                def __init__(self):
                    super().__init__()
                    self.enc = SiglipVisionModel(SiglipVisionConfig(**cfg["encoder"]))
                    self.inp = nn.Sequential(nn.Linear(self.enc.config.hidden_size + 5, d), nn.GELU(), nn.Dropout(0.1))
                    self.page = nn.TransformerEncoder(nn.TransformerEncoderLayer(d, 4, d * 2, 0.1, batch_first=True, norm_first=True), 2, enable_nested_tensor=False)
                    self.heads = nn.ModuleList(nn.Linear(d, len(cfg[k])) for k in ("skew", "stretch"))

                def forward(self, x, geo):
                    h = self.inp(torch.cat([self.enc(pixel_values=x).pooler_output, geo], 1))
                    h = self.page(h[None])[0]   # 한 쪽의 효과음끼리 서로 보게 한다
                    return [head(h) for head in self.heads]

            net = Net()
            net.load_state_dict(load_file(os.path.join(path, "model.safetensors")))
            cuda = torch.cuda.is_available()
            _net = (net.to("cuda" if cuda else "cpu", torch.float16 if cuda else torch.float32).eval(), cfg)
    return _net


#page: PIL 페이지(RGB), boxes: 한 쪽의 효과음 글자 상자들 (x1, y1, x2, y2). → 상자마다 {font, skew, small, stretch}
def predict(page, boxes):
    if not boxes:
        return []
    import math
    import numpy as np, torch
    from PIL import Image
    net, cfg = load()
    W, H = page.size
    S = cfg["crop"]
    xs, geo = [], []
    for x1, y1, x2, y2 in boxes:
        m = int(cfg["margin"] * max(x2 - x1, y2 - y1))   # 학습 때와 같게: 상자를 조금 넓혀 자르고, 흰 정사각형 가운데에 비율 유지로 넣는다
        crop = page.crop((max(0, x1 - m), max(0, y1 - m), min(W, x2 + m), min(H, y2 + m)))
        s = S / max(crop.size)
        crop = crop.resize((max(1, round(crop.width * s)), max(1, round(crop.height * s))), Image.BICUBIC)
        canvas = Image.new("RGB", (S, S), (255, 255, 255))
        canvas.paste(crop, ((S - crop.width) // 2, (S - crop.height) // 2))
        xs.append(np.asarray(canvas))
        geo.append([(x1 + x2) / 2 / W, (y1 + y2) / 2 / H, (x2 - x1) / W, (y2 - y1) / H, math.log((x2 - x1) / max(1, y2 - y1))])
    p = next(net.parameters())
    x = torch.from_numpy(np.stack(xs)).to(p.device).permute(0, 3, 1, 2).float() / 255
    x = torch.nn.functional.interpolate(x, size=cfg["size"], mode="bilinear", align_corners=False)
    mean, std = (torch.tensor(cfg[k], device=p.device).view(1, 3, 1, 1) for k in ("mean", "std"))
    with torch.no_grad():
        out = [o.argmax(-1).tolist() for o in net(((x - mean) / std).to(p.dtype), torch.tensor(geo, device=p.device, dtype=p.dtype))]
    return [dict(font=FONT, skew=cfg["skew"][a], small=SMALL, stretch=cfg["stretch"][b]) for a, b in zip(*out)]
