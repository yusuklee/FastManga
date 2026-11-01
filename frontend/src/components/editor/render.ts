import type { Content, FontChoice } from "../../Project";

//영역: 말풍선(bubble) 안쪽 INSET, 없으면 글자 상자
//글자 크기: 원본 글자 크기(font_size)에서 시작해, 영역에 들어가는 가장 큰 크기를 이분 탐색으로 찾는다
//줄바꿈: 띄어쓰기에서만 (keep-all). 단어 하나가 폭보다 길면 그때만 글자 단위
const FALLBACK = "Malgun Gothic, sans-serif";
import { FONT_URL } from "../../api";
const WEIGHT = 700;
const LINE_HEIGHT = 1.25;
const INSET = 4;
const MIN_SIZE = 8;

const IMAGE_CACHE_MAX = 8;
const imageCache = new Map<string, Promise<HTMLImageElement>>();

//이미지 URL → 디코드된 Image. 같은 URL 은 한 번만 받는다
export function loadImage(src: string) {
  let p = imageCache.get(src);
  if (p) {
    imageCache.delete(src); //최근 사용으로 순서 갱신
  } else {
    p = new Promise<HTMLImageElement>((resolve, reject) => {
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = () => resolve(img);
      img.onerror = () => {
        imageCache.delete(src); //실패한 건 캐시에 남기지 않는다 (다음에 다시 시도)
        reject(new Error(`image load failed: ${src.slice(0, 60)}`));
      };
      img.src = src;
    });
  }
  imageCache.set(src, p);
  while (imageCache.size > IMAGE_CACHE_MAX) {
    const oldest = imageCache.keys().next().value!;
    imageCache.delete(oldest);
  }
  return p;
}

const loadedFonts = new Set<string>();

export async function ensureFont(font: FontChoice) {
  if (!font.regular || loadedFonts.has(font.family)) return;
  const faces = [new FontFace(font.family, `url("${FONT_URL}${font.regular}")`, { weight: "100 900" })];
  if (font.bold) faces.push(new FontFace(font.family, `url("${FONT_URL}${font.bold}")`, { weight: "700" }));
  for (const f of faces) document.fonts.add(await f.load());
  loadedFonts.add(font.family);
}

const fontSpec = (size: number, family: string) => `${WEIGHT} ${size}px "${family}", ${FALLBACK}`;

//글을 maxW 폭에 맞게 줄로 나눈다. \n 은 무조건 줄바꿈
function wrapLines(ctx: CanvasRenderingContext2D, text: string, maxW: number) {
  const fits = (s: string) => ctx.measureText(s).width <= maxW;
  const lines: string[] = [];
  for (const para of text.split("\n")) {
    let line = "";
    for (const word of para.split(" ")) {
      const cand = line ? `${line} ${word}` : word;
      if (fits(cand)) {
        line = cand;
        continue;
      }
      if (line) lines.push(line);
      if (fits(word)) {
        line = word;
        continue;
      }
      //단어 하나가 폭보다 김 → 글자 단위로
      let cur = "";
      for (const ch of word) {
        if (!cur || fits(cur + ch)) cur += ch;
        else {
          lines.push(cur);
          cur = ch;
        }
      }
      line = cur;
    }
    lines.push(line);
  }
  return lines;
}

function wrapVar(ctx: CanvasRenderingContext2D, text: string, widthAt: (i: number) => number) {
  const lines: string[] = [];
  const fits = (s: string) => ctx.measureText(s).width <= widthAt(lines.length);
  for (const para of text.split("\n")) {
    let line = "";
    for (const word of para.split(" ")) {
      const cand = line ? `${line} ${word}` : word;
      if (fits(cand)) { line = cand; continue; }
      if (line) lines.push(line);
      if (fits(word)) { line = word; continue; }
      let cur = "";
      for (const ch of word) {
        if (!cur || fits(cur + ch)) cur += ch;
        else { lines.push(cur); cur = ch; }
      }
      line = cur;
    }
    lines.push(line);
  }
  return lines;
}

//영역에 맞는 글자 크기와 줄 목록. 이분 탐색으로 맞는 최대 크기를 찾는다
//shape 가 있으면 (말풍선 안쪽을 줄마다 잰 폭·가운데) 각 줄이 그 줄 높이의 폭 안에 들어가야 맞는 것으로 본다
type Shape = { left: Float32Array; right: Float32Array };
function layout(ctx: CanvasRenderingContext2D, text: string, family: string, start: number, w: number, h: number, shape?: Shape) {
  const slot = (n: number, i: number, step: number) => {
    const top = h / 2 - (n * step) / 2 + i * step;
    if (!shape) return { width: w, center: w / 2 };
    let l = 0, r = w;
    for (let y = Math.max(0, Math.floor(top)); y < Math.min(h, Math.ceil(top + step)); y++) {
      l = Math.max(l, shape.left[y]);
      r = Math.min(r, shape.right[y]);
    }
    return { width: Math.max(0, r - l), center: (l + r) / 2 };
  };
  const tryFit = (size: number) => {
    ctx.font = fontSpec(size, family);
    const step = size * LINE_HEIGHT;
    let lines = wrapLines(ctx, text, w);
    for (let k = 0; shape && k < 3; k++) {
      const n = lines.length;
      const next = wrapVar(ctx, text, (i) => slot(n, i, step).width);
      if (next.length === n) { lines = next; break; }
      lines = next;
    }
    const n = lines.length;
    const slots = lines.map((_, i) => slot(n, i, step));
    const ok = n * step <= h + 0.5 && lines.every((l, i) => ctx.measureText(l).width <= slots[i].width + 0.5);
    return { ok, lines, centers: slots.map((sl) => sl.center) };
  };
  let lo = MIN_SIZE, hi = Math.max(MIN_SIZE, Math.round(start));
  const first = tryFit(MIN_SIZE);
  let best = { size: MIN_SIZE, lines: first.lines, centers: first.centers };
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const r = tryFit(mid);
    if (r.ok) {
      best = { size: mid, lines: r.lines, centers: r.centers };
      lo = mid + 1;
    } else hi = mid - 1;
  }
  return best;
}

//말풍선 안쪽을 줄마다 잰다: 가운데 색과 비슷한 픽셀이 가운데에서 좌우로 이어지는 데까지 (글자는 이미 지워져 있다)
function bubbleShape(ctx: CanvasRenderingContext2D, x1: number, y1: number, w: number, h: number): Shape | undefined {
  let data: Uint8ClampedArray;
  try { data = ctx.getImageData(Math.round(x1), Math.round(y1), Math.round(w), Math.round(h)).data; } catch { return undefined; }
  const W = Math.round(w), H = Math.round(h);
  if (W < 8 || H < 8) return undefined;
  const px = (x: number, y: number) => 4 * (y * W + x);
  const cx = W >> 1, cy = H >> 1;
  const c = px(cx, cy);
  const [r0, g0, b0] = [data[c], data[c + 1], data[c + 2]];
  const same = (x: number, y: number) => { const p = px(x, y); return Math.abs(data[p] - r0) + Math.abs(data[p + 1] - g0) + Math.abs(data[p + 2] - b0) < 90; };
  const left = new Float32Array(H), right = new Float32Array(H);
  const pad = 4;
  for (let y = 0; y < H; y++) {
    if (!same(cx, y)) { left[y] = cx; right[y] = cx; continue; }
    let l = cx, r = cx;
    while (l > 0 && same(l - 1, y)) l--;
    while (r < W - 1 && same(r + 1, y)) r++;
    left[y] = Math.min(cx, l + pad);
    right[y] = Math.max(cx, r - pad);
  }
  const widths = Array.from(right, (r, y) => r - left[y]).sort((a, b) => a - b);
  if (widths[H >> 1] < 0.3 * W) return undefined;   //가운데가 말풍선 바탕이 아님 (안 지운 그림 등)
  return { left, right };
}

//페이지 하나를 canvas 에 그린다: 이미지 + (translated 가 있는 상자마다) 번역문
export function renderPage(
  canvas: HTMLCanvasElement,
  image: HTMLImageElement,
  contents: Content[],
  font: FontChoice,
  withText: boolean
) {
  canvas.width = image.naturalWidth;
  canvas.height = image.naturalHeight;
  const ctx = canvas.getContext("2d")!;
  ctx.drawImage(image, 0, 0);
  if (!withText) return;

  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.lineJoin = "round";
  //탐지가 같은 대사를 합친 상자와 줄마다 낸 상자로 겹쳐 내면, 큰 상자 안에 대부분 들어간 작은 상자는 그리지 않는다
  const area = (b: number[]) => Math.max(0, b[2] - b[0]) * Math.max(0, b[3] - b[1]);
  const inter = (a: number[], b: number[]) => Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0])) * Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));
  const shown = contents.filter((c) => c.translated);
  const drawn = shown.filter((c) => !shown.some((o) => o !== c && area(o.pos) > area(c.pos) && inter(o.pos, c.pos) > 0.6 * area(c.pos)));
  for (const c of drawn) {
    const [x1, y1, x2, y2] = c.bubble
      ? [c.bubble[0] + INSET, c.bubble[1] + INSET, c.bubble[2] - INSET, c.bubble[3] - INSET]
      : c.pos;
    const w = Math.max(1, x2 - x1), h = Math.max(1, y2 - y1);
    const family = c.font ?? font.family;
    //크기를 직접 정했으면(c.size) 영역에 맞추지 않고 그 크기로 (넘쳐도 그대로)
    const shape = c.bubble ? bubbleShape(ctx, x1, y1, w, h) : undefined;
    const { size, lines, centers } = c.size
      ? { size: c.size, lines: (ctx.font = fontSpec(c.size, family), wrapLines(ctx, c.translated!, w)), centers: undefined as number[] | undefined }
      : layout(ctx, c.translated!, family, c.font_size ?? Math.min(w, h), w, h, shape);

    ctx.font = fontSpec(size, family);
    const step = size * LINE_HEIGHT;
    //원본 줄이 기울어져 있으면(angle, 시계 방향 +) 상자 가운데를 축으로 돌려서 찍는다
    ctx.save();
    ctx.translate(x1 + w / 2, y1 + h / 2);
    if (c.angle) ctx.rotate((c.angle * Math.PI) / 180);
    const top = -(lines.length * step) / 2;
    lines.forEach((line, i) => {
      const y = top + (i + 0.5) * step;
      const x = centers ? centers[i] - w / 2 : 0;
      if (c.stroke) {
        ctx.strokeStyle = c.stroke;
        ctx.lineWidth = Math.max(2, size / 6);   // DOM 의 8방향 그림자(size/12)와 같은 두께
        ctx.strokeText(line, x, y);
      }
      ctx.fillStyle = c.color ?? "#000";
      ctx.fillText(line, x, y);
    });
    ctx.restore();
  }
}

export async function renderToPng(src: string, contents: Content[], font: FontChoice) {
  const canvas = document.createElement("canvas");
  renderPage(canvas, await loadImage(src), contents, font, true);
  return new Promise<Blob>((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("PNG 인코딩 실패"))), "image/png")
  );
}

//배열을 n 개씩 동시에 처리 (코하루의 buffer_unordered(4) 와 같은 역할)
export async function parallel<T>(items: T[], n: number, work: (item: T, i: number) => Promise<void>) {
  let next = 0;
  const worker = async () => {
    while (next < items.length) {
      const i = next++;
      await work(items[i], i);
    }
  };
  await Promise.all(Array.from({ length: Math.min(n, items.length) }, worker));
}
