#사람이 그린 효과음 상자의 글자 마스크: SAM 2.1 에 상자를 주면 그 안의 글자 모양(선+속)을 돌려준다
#(comic-text-detector 는 큰 속 빈 효과음의 윤곽선 조각만 잡는다. 11-13 f7 24페이지 도·퓻 으로 확인)
import threading
import numpy as np
import cv2

REPO, REV = "facebook/sam2.1-hiera-large", "665f8e2ad61cf5f53d65644ff27c8ee525124610"
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
            _model = Sam2Model.from_pretrained(path).to("cuda" if torch.cuda.is_available() else "cpu").eval()
            _processor = Sam2Processor.from_pretrained(path)
    return _model, _processor


#image: PIL 페이지, pos: 글자 상자. → (넓힌 영역 (x1, y1, x2, y2), 그 영역 크기의 bool 마스크 후보 3개, 후보마다 모델이 매긴 점수)
def candidates(image, pos):
    import torch
    model, processor = load()
    W, H = image.size
    x1, y1, x2, y2 = [int(v) for v in pos]
    px, py = max(16, int((x2 - x1) * PAD)), max(16, int((y2 - y1) * PAD))
    area = (max(0, x1 - px), max(0, y1 - py), min(W, x2 + px), min(H, y2 + py))
    crop = image.convert("RGB").crop(area)
    inputs = processor(images=crop, input_boxes=[[[x1 - area[0], y1 - area[1], x2 - area[0], y2 - area[1]]]], return_tensors="pt").to(model.device)
    with torch.no_grad():
        out = model(**inputs, multimask_output=True)
    masks = processor.post_process_masks(out.pred_masks.cpu(), inputs["original_sizes"])[0][0].numpy()
    return area, masks, out.iou_scores.cpu().numpy().ravel()


#대사 글자 크기: 글자 마스크(둘째 후보 = 셋 중 대체로 가장 넓게 잡는 것)를 감싼 가장 작은 직사각형 넓이 ÷ 글자 수 의 제곱근
#(글자 하나가 차지하는 정사각형의 한 변. 못 재면 0)
def text_size(mask, count):
    ys, xs = np.nonzero(mask)
    if not count or len(xs) < 10:
        return 0
    w, h = cv2.minAreaRect(np.stack([xs, ys], 1).astype(np.float32))[1]
    return round((w * h / count) ** 0.5)


#사람이 그린 효과음 상자의 글자 마스크. → (넓힌 영역 (x1, y1, x2, y2), 그 영역 크기의 bool 마스크)
def letter_mask(image, pos):
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
