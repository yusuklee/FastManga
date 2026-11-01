import threading

REPO, REV = "JustANormalTinkerer/hayai-ocr-v2.5-nova", "2803d0dc005fa4396ab1e7c5a472d2c450a247f7"
PROC_REPO, PROC_REV = "google/siglip2-base-patch16-naflex", "b53b807d3a2d5e2b3911292f2d69e5341cdc064c"
PATTERNS = ["*.json", "*.py", "*.safetensors", "*.txt"]
PROC_PATTERNS = ["*.json", "*.txt", "*.model"]

_model = _processor = _tokenizer = None
_lock = threading.RLock()


def load():
    global _model, _processor, _tokenizer
    with _lock:
        if _model is None:
            import torch
            from huggingface_hub import snapshot_download
            from transformers import AutoConfig, AutoModel, AutoProcessor, PreTrainedTokenizerFast, Siglip2VisionConfig
            path = snapshot_download(REPO, revision=REV, allow_patterns=PATTERNS)
            proc = snapshot_download(PROC_REPO, revision=PROC_REV, allow_patterns=PROC_PATTERNS)
            config = AutoConfig.from_pretrained(path, trust_remote_code=True)
            config.vision_config = Siglip2VisionConfig.from_pretrained(proc).to_dict()
            _model = AutoModel.from_pretrained(path, config=config, trust_remote_code=True).to("cuda" if torch.cuda.is_available() else "cpu").eval()
            _processor = AutoProcessor.from_pretrained(proc)
            _tokenizer = PreTrainedTokenizerFast.from_pretrained(path)
    return _model, _processor, _tokenizer


#조각 그림들 → 글자. 4개씩 한 번에
def recognize(crops, batch=4):
    if not crops:
        return []
    import torch
    with _lock, torch.inference_mode():
        model, processor, tokenizer = load()
        words = []
        for i in range(0, len(crops), batch):
            inputs = processor(images=[c.convert("RGB") for c in crops[i:i + batch]], max_num_patches=384, return_tensors="pt").to(model.device)
            texts = model.generate(pixel_values=inputs["pixel_values"], pixel_attention_mask=inputs["pixel_attention_mask"],
                                   spatial_shapes=inputs["spatial_shapes"], tokenizer=tokenizer, max_new_tokens=256, repetition_penalty=1.0)
            words += [str(t).strip() for t in texts]
        return words
