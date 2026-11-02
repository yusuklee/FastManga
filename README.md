<h1 align="center">FastManga</h1>

<p align="center">
<a href="https://github.com/yusuklee/FastManga/releases/latest/download/Install-FastManga.exe"><img alt="Download" src="https://img.shields.io/github/v/release/yusuklee/FastManga?style=for-the-badge&label=Download&color=f2760a"></a>
</p>

---

 Detection, OCR and inpainting run locally on your GPU. Translation uses Gemini, Claude, ChatGPT or a local model with your own API key.

## Install

1. [Download Install-FastManga.exe](https://github.com/yusuklee/FastManga/releases/latest/download/Install-FastManga.exe) and run it. No admin rights needed.
2. The first start downloads PyTorch with CUDA (about 3 GB, one time, from the same release) and shows the progress. The first time you press **PROCESS** it downloads the detection and OCR models (about 0.8 GB).
3. Open **Settings** and paste your API key ([Gemini](https://aistudio.google.com/apikey), [Claude](https://platform.claude.com/settings/keys) or OpenAI).

When a new version is released the app shows an **Update now** bar on the start screen; it downloads the new Setup, installs it in place and restarts. Packages, models and projects are kept.

Packages, models and your projects stay inside the app folder (`%LOCALAPPDATA%\Programs\FastManga`). Uninstall from Windows Settings → Apps; it asks whether to delete your projects too.

> [!NOTE]
> Works on any Windows 10/11 PC. With an NVIDIA GPU (driver 570 or newer, no CUDA toolkit needed) a page takes about a second. Without one it falls back to the CPU and is much slower.

## setup

![스크린샷 2026-09-25 005338.png](guide_imgs/%EC%8A%A4%ED%81%AC%EB%A6%B0%EC%83%B7%202026-09-25%20005338.png)![alt text](<스크린샷 2026-09-25 005338.png>)

---

![스크린샷 2026-09-25 005357.png](guide_imgs/%EC%8A%A4%ED%81%AC%EB%A6%B0%EC%83%B7%202026-09-25%20005357.png)![alt text](<스크린샷 2026-09-25 005357.png>)

---
![스크린샷 2026-09-25 005427.png](guide_imgs/%EC%8A%A4%ED%81%AC%EB%A6%B0%EC%83%B7%202026-09-25%20005427.png)![alt text](<스크린샷 2026-09-25 005427.png>)

---

![설정 버튼 위치.png](guide_imgs/%EC%84%A4%EC%A0%95%20%EB%B2%84%ED%8A%BC%20%EC%9C%84%EC%B9%98.png)![alt text](<설정 버튼 위치.png>)

---

![스크린샷 2026-09-25 010132.png](guide_imgs/%EC%8A%A4%ED%81%AC%EB%A6%B0%EC%83%B7%202026-09-25%20010132.png)![alt text](<스크린샷 2026-09-25 010132.png>)


## How it works

| Step | What happens | Model |
|---|---|---|
| Detect | Finds text, speech bubbles and onomatopoeia | RF-DETR |
| OCR | Reads the text in every box | HAYAI OCR (PaddleOCR-VL optional) |
| Translate | Sends the page text to the LLM you pick (Japanese → Korean by default, 38 languages available) | Gemini / Claude / ChatGPT / local |
| Erase | Removes the original text | LaMa |
| Render | Typesets the translation into the bubbles with the font you pick; sound effects are redrawn in a matching style | – (own model for sound effects) |
| Export | Writes the finished pages to a folder | – |



## Models

- Detection: [Koharu Layout RF-DETR Seg 2XL](https://huggingface.co/mayocream/koharu-layout-rfdetr-seg-2xl-1152)
- OCR: [HAYAI OCR v2.5](https://huggingface.co/JustANormalTinkerer/hayai-ocr-v2.5-nova), optional [PaddleOCR-VL](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6-GGUF)
- Text mask: [comic-text-detector](https://github.com/dmMaze/comic-text-detector)
- Inpainting: [LaMa (anime-manga-big-lama)](https://github.com/advimman/lama)
- Translation: Gemini flash models, Claude (Sonnet / Haiku / Opus), ChatGPT, or a local GGUF model via llama.cpp



## requirements

Python 3.13 and Node.js.

```
pip install -r requirements.txt -r requirements-models.txt
cd frontend && npm install && npm run build && cd ..
python -m fastapi dev backend.py     # API server (frontend: cd frontend && npm run dev)
python build/build.py 0.2.0          # portable zip + Setup.exe (needs Inno Setup)
```


## Acknowledgements

  - Text mask and layout approach: Koharu
  - Detection / OCR / inpainting models: linked above
