#효과음 상자의 글자 마스크: SAM 2.1 에 상자를 주면 그 안의 글자 모양(선+속)을 돌려준다 (대사는 comic-text-detector 마스크를 쓴다)
#(comic-text-detector 는 큰 속 빈 효과음의 윤곽선 조각만 잡는다. 11-13 f7 24페이지 도·퓻 으로 확인)
import threading   # numpy·cv2 는 함수 안에서 부른다 (setup.py 가 첫 실행 때 패키지를 받기 전에 이 파일을 읽는다)

REPO, REV = "yusuklee/sam2.1-hiera-large-fp16", "d3ac2c69e94d6bd0e3d47473d88d2a17544c9555"   # facebook/sam2.1-hiera-large (665f8e2) 를 16비트로만 바꾼 것 (받는 양 898MB → 449MB)
PATTERNS = ["*.json", "*.safetensors"]
PAD = 0.15   # 상자 둘레를 이만큼 넓혀 잘라서 모델에 보여준다 (글자가 상자 밖으로 조금 나가도 잡히게)

_model = _processor = None
_lock = threading.Lock()


def load():
    global _model, _processor
    with _lock:
        if _model is None:
            import torch
            from huggingface_hub import snapshot_download
            from transformers import Sam2Model, Sam2Processor
            path = snapshot_download(REPO, revision=REV, allow_patterns=PATTERNS)
            cuda = torch.cuda.is_available()   # GPU 에서는 전부 16비트(fp16)로 돌린다
            _model = Sam2Model.from_pretrained(path, dtype=torch.float16 if cuda else torch.float32).to("cuda" if cuda else "cpu").eval()
            _processor = Sam2Processor.from_pretrained(path)
    return _model, _processor


_cache = {}   # (조각 그림, 조각 안 상자) → (마스크 후보, 점수). OCR 때 구한 것을 효과음 렌더가 다시 쓴다 (같은 상자를 두 번 계산하지 않게)


#image: PIL 페이지, pos: 글자 상자. → (넓힌 영역 (x1, y1, x2, y2), 그 영역 크기의 bool 마스크 후보 3개, 후보마다 모델이 매긴 점수)
#GPU 에서는 16비트(fp16)로 돌린다 (2026-11-19 효과음 54개: 32비트와 마스크가 99.8% 겹치고 고르는 후보는 전부 같음. 1.7배 빠름)
def candidates(image, pos):
    import hashlib
    import torch
    W, H = image.size
    x1, y1, x2, y2 = [int(v) for v in pos]
    px, py = max(16, int((x2 - x1) * PAD)), max(16, int((y2 - y1) * PAD))
    area = (max(0, x1 - px), max(0, y1 - py), min(W, x2 + px), min(H, y2 + py))
    crop = image.crop(area).convert("RGB")
    box = [x1 - area[0], y1 - area[1], x2 - area[0], y2 - area[1]]
    key = (hashlib.md5(crop.tobytes()).digest(), *crop.size, *box)
    if key not in _cache:
        model, processor = load()
        inputs = processor(images=crop, input_boxes=[[box]], return_tensors="pt").to(model.device)
        with torch.no_grad():
            out = model(pixel_values=inputs["pixel_values"].to(model.dtype), input_boxes=inputs["input_boxes"].to(model.dtype), multimask_output=True)
        masks = processor.post_process_masks(out.pred_masks.float().cpu(), inputs["original_sizes"])[0][0].numpy()
        if len(_cache) >= 256:
            _cache.pop(next(iter(_cache)))
        _cache[key] = (masks, out.iou_scores.float().cpu().numpy().ravel())
    return (area, *_cache[key])


#효과음 상자의 글자 마스크 (선 + 속). → (넓힌 영역 (x1, y1, x2, y2), 그 영역 크기의 bool 마스크)
def letter_mask(image, pos):
    import numpy as np
    import cv2
    area, masks, scores = candidates(image, pos)
    best = masks[int(scores.argmax())]
    #속 빈 글자(ド)는 선만 잡은 후보의 점수가 조금 더 높게 나온다 → 점수가 비슷하고(0.1 안) 그 후보를 품는 더 넓은 후보가 있으면 그쪽(속까지 잡은 것)을 쓴다
    #(11-13 f7 13페이지 효과음 13개로 확인: 바뀌는 건 6개, 검은 속·빠진 글자가 더 들어가는 쪽으로만 바뀜)
    for j in np.argsort([-m.sum() for m in masks]):
        if scores[j] >= scores.max() - 0.1 and (masks[j] & best).sum() >= 0.9 * best.sum():
            best = masks[j]
            break
    m = cv2.morphologyEx(best.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8)) > 0   # 마스크에 숭숭 난 작은 구멍을 메운다
    _, lab = cv2.connectedComponents((~m).astype(np.uint8), connectivity=4)   # 선으로 둘러싸인 속도 글자에 넣는다
    outside = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    return area, m | ~np.isin(lab, outside)
