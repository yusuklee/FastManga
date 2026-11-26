import type { Content, FontChoice } from "../../Project";

//영역: 말풍선(bubble) 안쪽 INSET (말풍선을 같이 쓰는 상자가 있으면 나눈 제 몫), 없으면 글자 상자
//글자 크기: 원본 글자 크기(font_size)에서 시작해, 영역에 들어가는 가장 큰 크기를 이분 탐색으로 찾는다
//줄바꿈: 띄어쓰기에서. 단어를 끊어야 훨씬 커지면(좁은 말풍선) 글자 단위로도
const FALLBACK = "Malgun Gothic, sans-serif";
import { FONT_URL } from "../../api";
const WEIGHT = 700;
const LINE_HEIGHT = 1.25;
const INSET = 4;
const MIN_SIZE = 8;
const KEEP_WORDS = 0.7;

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


//글을 줄로 나눈다 (i 번째 줄 폭 = widthAt(i)). \n 은 무조건 줄바꿈. broke = 단어 하나가 폭보다 길어서 글자 단위로 끊었음
function wrap(ctx: CanvasRenderingContext2D, text: string, widthAt: (i: number) => number) {
  const lines: string[] = [];
  let broke = false;
  const fits = (s: string) => ctx.measureText(s).width <= widthAt(lines.length);
  for (const para of text.split("\n")) {
    let line = "";
    for (const word of para.split(" ")) {
      const cand = line ? `${line} ${word}` : word;
      if (fits(cand)) { line = cand; continue; }
      if (line) lines.push(line);
      if (fits(word)) { line = word; continue; }
      broke = true;
      let cur = "";
      for (const ch of word) {
        if (!cur || fits(cur + ch)) cur += ch;
        else { lines.push(cur); cur = ch; }
      }
      line = cur;
    }
    lines.push(line);
  }
  return { lines, broke };
}

//영역에 맞는 글자 크기와 줄 목록. 이분 탐색으로 맞는 최대 크기를 찾는다
//shape 가 있으면 (말풍선 안쪽을 줄마다 잰 폭·가운데) 각 줄이 그 줄 높이의 폭 안에 들어가야 맞는 것으로 본다
type Shape = { left: Float32Array; right: Float32Array };
function layout(ctx: CanvasRenderingContext2D, text: string, family: string, start: number, w: number, h: number, shape?: Shape, cy = h / 2) {
  const slot = (n: number, i: number, step: number) => {
    const top = cy - (n * step) / 2 + i * step;
    if (!shape) return { width: w, center: w / 2 };
    let l = 0, r = w;
    for (let y = Math.max(0, Math.floor(top)); y < Math.min(h, Math.ceil(top + step)); y++) {
      l = Math.max(l, shape.left[y]);
      r = Math.min(r, shape.right[y]);
    }
    return { width: Math.max(0, r - l), center: (l + r) / 2 };
  };
  const tryFit = (size: number, mayBreak: boolean) => {
    ctx.font = fontSpec(size, family);
    const step = size * LINE_HEIGHT;
    let r = wrap(ctx, text, () => w);
    for (let k = 0; shape && k < 3; k++) {
      const n = r.lines.length;
      r = wrap(ctx, text, (i) => slot(n, i, step).width);
      if (r.lines.length === n) break;
    }
    const lines = r.lines, n = lines.length;
    const slots = lines.map((_, i) => slot(n, i, step));
    const ok = (mayBreak || !r.broke) && cy - (n * step) / 2 >= -0.5 && cy + (n * step) / 2 <= h + 0.5 && lines.every((l, i) => ctx.measureText(l).width <= slots[i].width + 0.5);
    return { ok, lines, centers: slots.map((sl) => sl.center) };
  };
  const search = (mayBreak: boolean) => {
    let lo = MIN_SIZE, hi = Math.max(MIN_SIZE, Math.round(start));
    const first = tryFit(MIN_SIZE, mayBreak);
    let best = { size: MIN_SIZE, lines: first.lines, centers: first.centers };
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      const r = tryFit(mid, mayBreak);
      if (r.ok) {
        best = { size: mid, lines: r.lines, centers: r.centers };
        lo = mid + 1;
      } else hi = mid - 1;
    }
    return best;
  };
  //단어를 안 끊고 들어가는 크기가 끊어서 들어가는 크기의 KEEP_WORDS 이상이면 안 끊는다 (좁은 세로 말풍선은 끊어야 커진다)
  const broken = search(true), whole = search(false);
  return whole.size >= broken.size * KEEP_WORDS ? whole : broken;
}

//RF 말풍선 모양(bubble_mask)을 줄마다 안쪽 구간 [시작, 끝, 시작, 끝, ...] 으로 줄여 둔다 (마스크 픽셀을 다 들고 있지 않게)
//뒤 그림이 비치는 말풍선도 그림 선과 상관없이 모양대로 잴 수 있다. renderPage 전에 loadMasks 로 채운다
const maskRows = new Map<string, number[][]>();
export async function loadMasks(contents: Content[]) {
  if (maskRows.size > 3000) maskRows.clear();
  await Promise.all(contents.filter((c) => c.bubble_mask && !maskRows.has(c.bubble_mask)).map(async (c) => {
    const bmp = await createImageBitmap(await (await fetch(`data:image/png;base64,${c.bubble_mask}`)).blob());
    const g = new OffscreenCanvas(bmp.width, bmp.height).getContext("2d")!;
    g.drawImage(bmp, 0, 0);
    const d = g.getImageData(0, 0, bmp.width, bmp.height).data, W = bmp.width;
    const rows: number[][] = [];
    for (let y = 0; y < bmp.height; y++) {
      const runs: number[] = [];
      for (let x = 0; x < W; x++) {
        const on = d[4 * (y * W + x)] > 127;
        if (on && runs.length % 2 === 0) runs.push(x);
        else if (!on && runs.length % 2 === 1) runs.push(x - 1);
      }
      if (runs.length % 2 === 1) runs.push(W - 1);
      rows.push(runs);
    }
    maskRows.set(c.bubble_mask!, rows);
  }));
}
const EDGE = 10;   //말풍선 모양 끝에서 이만큼 안쪽까지 (테두리 선 두께 + 여유)
//dx, dy: 그릴 영역 왼쪽 위가 말풍선 상자(마스크) 왼쪽 위에서 떨어진 만큼 (말풍선을 나눈 몫이면 더 크다)
//줄마다 그릴 영역 가운데에 가장 가까운 구간을 쓴다 (말풍선 둘이 붙어 한 모양으로 잡혀도 제 쪽 말풍선을 잰다)
function maskShape(rows: number[][], dx: number, dy: number, w: number, h: number): Shape {
  const left = new Float32Array(h), right = new Float32Array(h), cx = w / 2, mx = dx + cx;
  for (let y = 0; y < h; y++) {
    const runs = rows[y + dy] ?? [];
    let best = -1, dist = Infinity;
    for (let i = 0; i < runs.length; i += 2) {
      const dd = mx < runs[i] ? runs[i] - mx : mx > runs[i + 1] ? mx - runs[i + 1] : 0;
      if (dd < dist) { dist = dd; best = i; }
    }
    const L = best < 0 ? 0 : Math.max(0, runs[best] - dx + EDGE), R = best < 0 ? 0 : Math.min(w, runs[best + 1] - dx - EDGE);
    const ok = best >= 0 && R - L > 0;
    left[y] = ok ? L : cx;
    right[y] = ok ? R : cx;
  }
  return { left, right };
}

//마스크가 없을 때(예전 프로젝트): 말풍선 안쪽을 지운 이미지에서 줄마다 잰다. 가운데 색과 비슷한 픽셀이 가운데에서 좌우로 이어지는 데까지
//밝은 말풍선은 뒤 그림이 옅게 비칠 수 있어서, 밝은 픽셀이면 안쪽으로 보고 어두운 테두리에서 멈춘다
const LIGHT = 150;
function bubbleShape(ctx: CanvasRenderingContext2D, x1: number, y1: number, w: number, h: number): Shape | undefined {
  let data: Uint8ClampedArray;
  try { data = ctx.getImageData(Math.round(x1), Math.round(y1), Math.round(w), Math.round(h)).data; } catch { return undefined; }
  const W = Math.round(w), H = Math.round(h);
  if (W < 8 || H < 8) return undefined;
  const px = (x: number, y: number) => 4 * (y * W + x);
  const lum = (p: number) => (data[p] + data[p + 1] + data[p + 2]) / 3;
  const cx = W >> 1, cy = H >> 1;
  const c = px(cx, cy);
  const [r0, g0, b0] = [data[c], data[c + 1], data[c + 2]];
  const light = lum(c) > LIGHT;
  const same = (x: number, y: number) => { const p = px(x, y); return light ? lum(p) > LIGHT : Math.abs(data[p] - r0) + Math.abs(data[p + 1] - g0) + Math.abs(data[p + 2] - b0) < 90; };
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

//말풍선 없는 세로 글줄(일본어 세로쓰기)은 그대로면 한국어를 한 글자씩 쌓게 된다 → 좌우로 넓혀 가로로 쓴다
//넓이는 높이의 WIDEN 배까지, 옆 상자(세로로 겹치는 것)와 페이지 끝은 넘지 않는다
const WIDEN = 0.6, GAP = 8;
function widen(pos: number[], contents: Content[], pageW: number) {
  const [x1, y1, x2, y2] = pos;
  if (y2 - y1 < 2.5 * (x2 - x1)) return pos;
  const cx = (x1 + x2) / 2, half = Math.max(x2 - x1, (y2 - y1) * WIDEN) / 2;
  let l = Math.max(0, cx - half), r = Math.min(pageW, cx + half);
  for (const o of contents) {
    if (o.pos === pos || o.pos[1] >= y2 || o.pos[3] <= y1) continue;
    if (o.pos[2] <= x1) l = Math.max(l, o.pos[2] + GAP);
    else if (o.pos[0] >= x2) r = Math.min(r, o.pos[0] - GAP);
  }
  return [Math.min(l, x1), y1, Math.max(r, x2), y2];
}

//말풍선 하나에 상자가 여럿이면(탐지·사용자 상자 모두) 서로 사이의 가운데 선으로 말풍선을 나눠 제 몫에만 쓴다
//(옆으로 떨어져 있으면 세로선, 위아래로 떨어져 있으면 가로선)
function bubbleArea(c: Content, all: Content[]) {
  const base = c.bubble_area ?? c.bubble!, key = base.join();
  let [x1, y1, x2, y2] = base;
  for (const o of all) {
    if (o === c || !o.bubble || (o.bubble_area ?? o.bubble).join() !== key) continue;
    const p = c.pos, q = o.pos;
    if (Math.max(q[0] - p[2], p[0] - q[2]) >= Math.max(q[1] - p[3], p[1] - q[3])) {
      if (q[0] > p[0]) x2 = Math.min(x2, (p[2] + q[0]) / 2); else x1 = Math.max(x1, (q[2] + p[0]) / 2);
    } else if (q[1] > p[1]) y2 = Math.min(y2, (p[3] + q[1]) / 2);
    else y1 = Math.max(y1, (q[3] + p[1]) / 2);
  }
  return [x1 + INSET, y1 + INSET, x2 - INSET, y2 - INSET];
}

//페이지 하나를 canvas 에 그린다: 이미지 + (translated 가 있는 상자마다) 번역문
//all: 페이지의 상자 전부 (효과음처럼 여기서 안 그리는 것도). 말풍선 나누기·넓히기에서 피할 자리
function luminance(hex: string) {
  const h = hex.replace("#", "");
  const v = (h.length === 3 ? h.split("").map((x) => x + x) : h.match(/../g) ?? ["00", "00", "00"]).slice(0, 3).map((x) => parseInt(x, 16) / 255);
  const [r, g, b] = v.map((x) => (x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function contrast(a: string, b: string) {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

//화면에 그려진 번역 글자 하나의 자리: (cx, cy) 를 축으로 angle(도, 시계 방향) 만큼 돌린 좌표에서 (x, y) 부터 w×h. 이 자리를 눌러 글자를 고르고 끌어 옮긴다
export type Frame = { cx: number; cy: number; x: number; y: number; w: number; h: number; angle: number };

//돌려주는 것: 상자 id → 그 번역문이 그려진 자리
export function renderPage(
  canvas: HTMLCanvasElement,
  image: HTMLImageElement,
  contents: Content[],
  font: FontChoice,
  withText: boolean,
  all: Content[] = contents
) {
  const frames = new Map<number, Frame>();
  canvas.width = image.naturalWidth;
  canvas.height = image.naturalHeight;
  const ctx = canvas.getContext("2d")!;
  ctx.drawImage(image, 0, 0);
  if (!withText) return frames;

  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.lineJoin = "round";
  //탐지가 같은 대사를 합친 상자와 줄마다 낸 상자로 겹쳐 내면, 큰 상자 안에 대부분 들어간 작은 상자는 그리지 않는다
  //(사용자가 그린 상자는 탐지 중복이 아니니 다른 상자를 가리지 않는다. 큰 효과음 상자 안의 대사 등)
  const area = (b: number[]) => Math.max(0, b[2] - b[0]) * Math.max(0, b[3] - b[1]);
  const inter = (a: number[], b: number[]) => Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0])) * Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));
  const shown = contents.filter((c) => c.translated);
  const drawn = shown.filter((c) => !shown.some((o) => o !== c && !o.user && area(o.pos) > area(c.pos) && inter(o.pos, c.pos) > 0.6 * area(c.pos)));
  for (const c of drawn) {
    const [x1, y1, x2, y2] = c.bubble ? bubbleArea(c, all) : widen(c.pos, all, canvas.width);
    const w = Math.max(1, x2 - x1), h = Math.max(1, Math.floor(y2 - y1));
    const family = c.font ?? font.family;
    //크기를 직접 정했으면(c.size) 영역에 맞추지 않고 그 크기로 (넘쳐도 그대로)
    const rows = c.bubble && c.bubble_mask && c.bubble_area ? maskRows.get(c.bubble_mask) : undefined;
    const shape = !c.bubble ? undefined : rows ? maskShape(rows, Math.round(x1 - c.bubble_area![0]), Math.round(y1 - c.bubble_area![1]), w, h) : bubbleShape(ctx, x1, y1, w, h);
    //글은 원래 글자 상자의 세로 가운데를 기준으로 쌓는다 (말풍선 둘이 한 모양으로 잡혀도 제 말풍선 자리에. 말풍선 밖 줄은 폭이 0이라 안 쓴다)
    const cy = Math.min(h, Math.max(0, (c.pos[1] + c.pos[3]) / 2 - y1));
    const { size, lines, centers } = c.size
      ? { size: c.size, lines: (ctx.font = fontSpec(c.size, family), wrap(ctx, c.translated!, () => w).lines), centers: undefined as number[] | undefined }
      : layout(ctx, c.translated!, family, c.font_size ?? Math.min(w, h), w, h, shape, cy);

    ctx.font = fontSpec(size, family);
    const step = size * LINE_HEIGHT;
    //원본 줄이 기울어져 있으면(angle, 시계 방향 +) 상자 가운데를 축으로 돌려서 찍는다. 사용자가 끌어 옮겼으면(move) 그만큼 옮긴다
    const ox = x1 + w / 2 + (c.move?.[0] ?? 0), oy = y1 + cy + (c.move?.[1] ?? 0), rot = c.angle ?? 0;
    ctx.save();
    ctx.translate(ox, oy);
    if (rot) ctx.rotate((rot * Math.PI) / 180);
    const top = -(lines.length * step) / 2;
    //글자색·테두리·굵기 (11-22 결정, 효과음과 같은 방식): 글자색 = 원본에서 잰 색, 테두리 = 흰색(글자와 대비 3 미만이면 #111111),
    //테두리는 말풍선 밖 대사만, 굵기 = 글자 크기의 5.5% (0.35~4px), 획 굵기 = 폰트 그대로. 글자 목록에서 고른 색(color_set·stroke_set)이 있으면 그 색
    const color = c.color_set ?? c.color ?? "#000";
    const stroke = c.stroke_set !== undefined ? c.stroke_set : c.bubble ? null : contrast(color, "#ffffff") >= 3 ? "#ffffff" : "#111111";   // 말풍선 안 대사는 테두리 없음
    const edge = Math.round(Math.min(4, Math.max(0.35, size * 0.055)) * 10) / 10;
    const each = (draw: (line: string, x: number, y: number) => void) => lines.forEach((line, i) => draw(line, centers ? centers[i] - w / 2 : 0, top + (i + 0.5) * step));
    if (stroke) {
      ctx.strokeStyle = stroke;
      ctx.lineWidth = 2 * edge;
      each((line, x, y) => ctx.strokeText(line, x, y));
    }
    ctx.fillStyle = color;
    each((line, x, y) => ctx.fillText(line, x, y));
    const half = lines.map((line) => ctx.measureText(line).width / 2), mid = lines.map((_, i) => (centers ? centers[i] - w / 2 : 0));
    const left = Math.min(...mid.map((x, i) => x - half[i])), right = Math.max(...mid.map((x, i) => x + half[i]));
    frames.set(c.id, { cx: ox, cy: oy, x: left, y: top, w: right - left, h: lines.length * step, angle: rot });
    ctx.restore();
  }
  return frames;
}

export async function renderToPng(src: string, contents: Content[], font: FontChoice) {
  const canvas = document.createElement("canvas");
  const image = await loadImage(src);
  await loadMasks(contents);
  renderPage(canvas, image, contents, font, true);
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
