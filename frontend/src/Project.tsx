import { Group, Panel, Separator } from "react-resizable-panels";
import { Button } from "@/components/ui/button";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Text } from "./components/editor/text";
import { SettingsDialog, DEFAULT_SETTINGS, PAGES_PER_CALL, loadKey, loadSettings, saveSettings, translateTarget, PROVIDERS, LOCAL_MODELS, type AppSettings } from "./components/editor/settings";
import { SplitButton } from "./components/editor/splitbutton";
import { PageList } from "./components/editor/pagelist";
import { RepeatButton } from "./components/editor/repeatbutton";
import { Toasts, describeError, type Toast } from "./components/editor/toast";
import { ensureFont, loadImage, renderPage, renderToPng, parallel } from "./components/editor/render";
import { pickFolder, saveToFolder, pageFileName, downloadZip, type ExportFile, isDesktopApp, pickFolderDesktop, saveToFolderDesktop } from "./components/editor/export";

import { API } from "./api";
import type { ProjectDetail } from "./App";

type area = [number, number, number, number];

//백엔드 /detect 응답 한 상자. translated 만 프런트가 채운다
export type Content = {
  id: number;
  pos: area; //글자 상자 (OCR·번역·렌더용)
  word: string; //원문
  translated?: string; //번역문
  page: number;
  mask?: string; //글자 모양 (base64 PNG), 지우기용
  mask_area?: area; //지우기용 넓힌 상자. mask 는 이 크기
  bubble?: area | null; //글자를 담은 말풍선 상자. 렌더 영역
  font_size?: number; //원본 글자 크기(px)
  angle?: number; //원본 줄의 기울기(도, 시계 방향 +). 렌더 때 이만큼 돌려서 찍는다
  user?: boolean; //＋ 로 직접 그린 상자. DETECT 를 다시 해도 남는다
  sfx?: boolean; //탐지가 의성어(효과음)로 분류한 상자
  font?: string; //이 상자만 쓸 폰트(family). 없으면 설정의 폰트
  size?: number; //이 상자만 쓸 글자 크기(px). 없으면 영역에 맞춰 자동
  color?: string; //글자색
  stroke?: string | null; //테두리색 (밝은 글자일 때)
};

//폰트 선택지. regular/bold 는 백엔드 /fontfiles/ 아래 상대 경로 (없으면 시스템 폰트)
export type FontChoice = { family: string; regular?: string | null; bold?: string | null };
const DEFAULT_FONT: FontChoice = { family: "Malgun Gothic" };

type PageContents = { [page: string]: Content[] };

//응답이 200 이 아니면 본문(백엔드 에러 내용)을 담아 던진다
const okJson = async (r: Response) => {
  if (!r.ok) throw new Error(`${r.status} ${(await r.text()).slice(0, 300)}`);
  return r.json();
};

//extra: 같이 보낼 폼 값 (detect 의 classes 등)
const post_image = async (path: string, page: string, contents?: Content[], extra: Record<string, string> = {}) => {
  const form = new FormData();
  form.append("file", await (await fetch(page)).blob(), "image.png");
  if (contents) form.append("contents", JSON.stringify(contents));
  for (const [k, v] of Object.entries(extra)) form.append(k, v);
  return fetch(`${API}/${path}`, { method: "POST", body: form }).then(okJson);
};

//인페인팅: 결과가 PNG 바이트로 오니 blob URL 로 받는다 (base64 문자열보다 작고 디코드가 없음)
//src: 지울 바탕 이미지 (기본은 원본 페이지)
const post_inpaint = async (path: string, page: string, contents: Content[], src = page) => {
  const form = new FormData();
  form.append("file", await (await fetch(src)).blob(), "image.png");
  form.append("contents", JSON.stringify(contents.map(({ pos, mask_area, mask }) => ({ pos, mask_area, mask }))));
  const r = await fetch(`${API}/${path}`, { method: "POST", body: form });
  if (!r.ok) throw new Error(`${r.status} ${(await r.text()).slice(0, 300)}`);
  return URL.createObjectURL(await r.blob());
};

//번역 요청 여러 개의 결과를 합친다: 성공한 것만 모으고, 실패가 있으면 첫 에러를 돌려준다
const settle = (res: PromiseSettledResult<Record<string, string>>[]) => {
  const translations: Record<string, string> = {};
  let error: unknown = undefined;
  for (const r of res) {
    if (r.status === "fulfilled") Object.assign(translations, r.value);
    else if (error === undefined) error = r.reason;
  }
  return { translations, error };
};
const sfxTargets = (contents: Content[]) => contents.filter((c) => c.sfx && c.translated?.trim());
const nonSfx = (contents: Content[]) => {
  const sfx = sfxTargets(contents);
  const area = (b: area) => Math.max(0, b[2] - b[0]) * Math.max(0, b[3] - b[1]);
  return contents.filter((c) => !c.sfx && !sfx.some((s) => {
    const ov = Math.max(0, Math.min(c.pos[2], s.pos[2]) - Math.max(c.pos[0], s.pos[0])) * Math.max(0, Math.min(c.pos[3], s.pos[3]) - Math.max(c.pos[1], s.pos[1]));
    return ov > 0.4 * Math.max(1, Math.min(area(c.pos), area(s.pos)));
  }));
};
const post_sfx = async (page: string, erased: string, contents: Content[]) => {
  const form = new FormData();
  form.append("file", await (await fetch(page)).blob(), "image.png");
  form.append("erased", await (await fetch(erased)).blob(), "erased.png");
  form.append("contents", JSON.stringify(sfxTargets(contents).map(({ pos, mask_area, word, translated }) => ({ pos, mask_area, word, translated }))));
  const r = await fetch(`${API}/sfx_render`, { method: "POST", body: form });
  if (!r.ok) throw new Error(`${r.status} ${(await r.text()).slice(0, 300)}`);
  return URL.createObjectURL(await r.blob());
};

export function Project({
  project,
  onBack,
}: {
  project: ProjectDetail; //백엔드가 디스크에서 읽어 준 프로젝트 (페이지 URL, 저장된 상자·번역, 지운 이미지)
  onBack: () => void;
}) {
  const name = project.name;
  //페이지 키 = 페이지 이미지 URL. 저장할 때는 파일명(file)으로 바꿔 쓴다
  const pages = useMemo(() => project.pages.map((p) => `${API}${p.url}`), [project]);
  const names = useMemo(() => project.pages.map((p) => p.name), [project]);
  const fileOf = useMemo(() => Object.fromEntries(project.pages.map((p) => [`${API}${p.url}`, p.file])) as Record<string, string>, [project]);
  const [selectedPage, setSelectedPage] = useState<string | null>(pages[0]);
  const [selectedPages, setSelectedPages] = useState<string[]>(pages[0] ? [pages[0]] : []);
  const anchor = useRef<string | null>(pages[0]);
  const targetPages = selectedPages.length ? selectedPages : selectedPage ? [selectedPage] : []; //PROCESS·EXPORT 대상
  const scrollRef = useRef<HTMLDivElement>(null);
  const toggleFullscreen = () => {
    if (document.fullscreenElement) document.exitFullscreen();
    else scrollRef.current?.requestFullscreen();
  };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (e.key === "ArrowUp" || e.key === "ArrowDown") {
        e.preventDefault();
        scrollRef.current?.scrollBy({ top: e.key === "ArrowDown" ? 160 : -160, behavior: "smooth" });
        return;
      }
      if (e.key === "f" || e.key === "F") {
        if (e.ctrlKey || e.metaKey || e.altKey) return; //Ctrl+F(찾기) 같은 건 건드리지 않음
        e.preventDefault();
        toggleFullscreen();
        return;
      }
      const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
      if (!step || !selectedPage) return;
      const i = pages.indexOf(selectedPage) + step;
      if (i < 0 || i >= pages.length) return;
      e.preventDefault();
      clickPage(pages[i], false, false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pages, selectedPage]);
  //처음 열 때(또는 페이지 목록이 바뀌었을 때) 현재 페이지가 목록에 없으면 1페이지를 선택
  useEffect(() => {
    if (pages.length && (!selectedPage || !pages.includes(selectedPage))) {
      setSelectedPage(pages[0]);
      setSelectedPages([pages[0]]);
      anchor.current = pages[0];
    }
  }, [pages]);
  const clickPage = useCallback((page: string, ctrl: boolean, shift: boolean) => {
    setSelectedPage(page);
    if (shift && anchor.current) {
      const [a, b] = [pages.indexOf(anchor.current), pages.indexOf(page)].sort((x, y) => x - y);
      setSelectedPages(pages.slice(a, b + 1));
      return;
    }
    anchor.current = page;
    if (ctrl) setSelectedPages((prev) => (prev.includes(page) ? prev.filter((p) => p !== page) : [...prev, page]));
    else setSelectedPages([page]);
  }, [pages]);
  const goPage = useCallback((page: string) => clickPage(page, false, false), [clickPage]); //REPEAT 자동 넘기기용
  const pageIndex = selectedPage ? pages.indexOf(selectedPage) : -1;
  const stepPage = (d: number) => {
    const i = pageIndex + d;
    if (i >= 0 && i < pages.length) goPage(pages[i]);
  };
  const [pageContents, setPageContents] = useState<PageContents>(() => {
    const out: PageContents = {};
    for (const p of project.pages) if (project.contents[p.file]) out[`${API}${p.url}`] = project.contents[p.file];
    return out;
  });
  const [selectedArea, setSelectedArea] = useState<string | null>(null);
  const [progress, setProgress] = useState(""); //진행 상황 / 에러 (하단 표시)
  const [callBar, setCallBar] = useState<boolean[] | null>(null); //TRANSLATE 중 호출별 도착 여부 (하단 칸 막대). null = 막대 없음
  type View = "original" | "inpainted" | "rendered";
  const [view, setView] = useState<View>("original");
  const [leftOpen, setLeftOpen] = useState(true);   //PAGES 패널 (VS Code 처럼 접으면 가운데가 넓어짐)
  const [fit, setFit] = useState<"width" | "page">("page"); //기본은 한 화면 맞춤
  const [fullscreen, setFullscreen] = useState(false);
  const windowFullscreen = useRef(false);
  useEffect(() => {
    const onChange = () => {
      const on = !!document.fullscreenElement;
      setFullscreen(on);
      if (isDesktopApp() && on !== windowFullscreen.current) {
        windowFullscreen.current = on;
        void window.pywebview!.api.fullscreen();
      }
    };
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);
  const [rightOpen, setRightOpen] = useState(true); //TEXT·SETTINGS 패널
  //설정 (⚙ 버튼으로 여는 창): 원본→번역 언어, 인페인팅 모델
  const [settings, setSettings] = useState<AppSettings>(() => {
    const { fontFamily: _f, ...saved } = loadSettings();
    //예전 버전에서 저장된 값이 지금 목록에 없으면 기본값으로
    const provider = saved.provider && saved.provider in PROVIDERS ? saved.provider : "gemini";
    const localModel = LOCAL_MODELS.some((m) => m.id === saved.localModel) ? saved.localModel! : DEFAULT_SETTINGS.localModel;
    const ocr = saved.ocr === "paddle" ? "paddle" : "hayai";
    const claudeModel = PROVIDERS.claude.models.includes(saved.claudeModel ?? "") ? saved.claudeModel! : DEFAULT_SETTINGS.claudeModel;
    return { ...DEFAULT_SETTINGS, ...saved, provider, localModel, ocr, claudeModel, apiKey: loadKey("gemini"), gptKey: loadKey("chatgpt"), claudeKey: loadKey("claude"), openaiKey: loadKey("openai") };
  });
  const target = translateTarget(settings);
  const modelName = target.model || settings.provider;
  const [settingsOpen, setSettingsOpen] = useState(false);
  const inpaintModel = "inpaint_lama";
  const translate = async (lines: { id: number; word: string }[]) => {
    const r = await fetch(`${API}/translate`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...target.headers },
      body: JSON.stringify({ lines, source: settings.source, target: settings.target, model: target.model, ...(target.model2 ? { model2: target.model2 } : {}), ...(target.baseUrl !== undefined ? { base_url: target.baseUrl } : {}), ...(target.local ? { local: true } : {}), ...(target.provider ? { provider: target.provider, effort: target.effort } : {}) }),
    });
    return await okJson(r);
  };
  //설정 창의 Gemini 모델 목록 (백엔드가 API 에서 받아옴)
  const [inpaintedImgs, setInpaintedImgs] = useState<{ [page: string]: string }>(() => {
    const out: Record<string, string> = {};
    for (const p of project.pages) if (project.erased[p.file]) out[`${API}${p.url}`] = `${API}${project.erased[p.file]}?t=${Date.now()}`;
    return out;
  }); //페이지별로 글자를 지운 이미지 (blob URL 또는 저장된 파일 URL)
  const [sfxImgs, setSfxImgs] = useState<{ [page: string]: string }>({}); //지운 이미지 위에 효과음까지 그린 것 (blob URL). 번역 뷰·내보내기의 바탕
  const sfxKeys = useRef<{ [page: string]: string }>({}); //마지막으로 그린 조건 (지운 이미지 + 효과음 번역문). 같으면 다시 안 그린다

  //자동 저장 (코하루처럼): 상자·번역이 바뀌면 0.8초 뒤 project.json 에 씀. 첫 렌더는 건너뜀
  const firstSave = useRef(true);
  useEffect(() => {
    if (firstSave.current) { firstSave.current = false; return; }
    const id = window.setTimeout(() => {
      const contents: Record<string, Content[]> = {};
      for (const [url, c] of Object.entries(pageContents)) if (fileOf[url]) contents[fileOf[url]] = c;
      fetch(`${API}/projects/${encodeURIComponent(name)}/state`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ contents }),
      }).catch(() => {});
    }, 800);
    return () => window.clearTimeout(id);
  }, [pageContents, fileOf, name]);

  //인페인팅 결과 저장/삭제 (PNG 파일로)
  const saveErased = async (page: string, url: string) => {
    const file = fileOf[page];
    if (!file) return;
    const blob = await (await fetch(url)).blob();
    await fetch(`${API}/projects/${encodeURIComponent(name)}/erased/${encodeURIComponent(file)}`, { method: "PUT", body: blob, headers: { "Content-Type": "image/png" } }).catch(() => {});
  };
  const deleteErased = (page: string) => {
    const file = fileOf[page];
    if (file) fetch(`${API}/projects/${encodeURIComponent(name)}/erased/${encodeURIComponent(file)}`, { method: "DELETE" }).catch(() => {});
  };

  //렌더 폰트. 기본은 시스템 Malgun Gothic, 나머지는 백엔드(/fonts)가 주는 koharu 내장 폰트
  const [font, set_font] = useState<FontChoice>(DEFAULT_FONT);
  const [allFont, setAllFont] = useState<FontChoice[]>([]);
  const fontChoices = useMemo(() => [DEFAULT_FONT, ...allFont], [allFont]);
  //설정·글꼴을 바꿀 때마다 localStorage 에. 글꼴 목록이 오면 저장해 둔 글꼴을 다시 고른다
  useEffect(() => saveSettings(settings, font.family), [settings, font.family]);
  useEffect(() => {
    const saved = loadSettings().fontFamily;
    const f = saved && fontChoices.find((c) => c.family === saved);
    if (f) set_font(f);
  }, [fontChoices]);

  //백엔드가 뜰 때까지 2초마다 확인하며 안내 문구를 띄운다
  const [backendUp, setBackendUp] = useState(false);
  useEffect(() => {
    let timer: number | undefined;
    const check = async () => {
      try {
        await fetch(`${API}/setup/status`).then(okJson);
        setBackendUp(true);
        setProgress((p) => (p.startsWith("Starting backend") ? "" : p));
      } catch {
        setProgress("Starting backend...");
        timer = window.setTimeout(check, 2000);
      }
    };
    check();
    return () => window.clearTimeout(timer);
  }, []);

  //처음 PROCESS 할 때 백엔드가 AI 패키지·모델을 받는다. 끝날 때까지 준비 창을 띄운다
  type SetupState = { state: string; text: string; pct: number | null };
  const [setup, setSetup] = useState<SetupState | null>(null);
  const prepareModels = async () => {
    let s: SetupState = await fetch(`${API}/setup/prepare`, { method: "POST" }).then(okJson);
    while (s.state !== "ready") {
      setSetup(s);
      if (s.state === "error") throw new Error(`Model setup: ${s.text}`);
      await new Promise((r) => setTimeout(r, 1000));
      s = await fetch(`${API}/setup/status`).then(okJson);
    }
    setSetup(null);
  };

  useEffect(() => {
    if (!backendUp) return;
    fetch(`${API}/fonts`)
      .then((r) => r.json())
      .then(setAllFont)
      .catch(() => {
        setAllFont([]);
      });
  }, [backendUp]);

//DETECT: 상자만 찾는다 (OCR 없음). ＋ 로 그린 상자는 지우지 않고 뒤에 붙인다
const handle_detect = async (page=selectedPage!)=>{
  setInpaintedImgs((prev)=>{
      const tmp = {...prev};
      if (tmp[page]?.startsWith("blob:")) URL.revokeObjectURL(tmp[page]); //이전 결과 메모리 해제
      delete tmp[page]
      return tmp;
  })
  deleteErased(page);
  setView("original");

  const detected:Content[] = await post_image("detect",page,undefined,{ classes: settings.onomatopoeia ? "text,onomatopoeia" : "text" });
  const users = (pageContents[page] ?? []).filter((c) => c.user).map((c, i) => ({ ...c, id: detected.length + i, word: "", translated: undefined }));
  const contents = [...detected, ...users];
  setPageContents((prev)=>({...prev,[page]:contents}))
  return contents
}

//OCR: 페이지의 상자 전부(탐지 + ＋)를 읽는다. 원문·지우기 마스크·글자 크기·색·기울기가 채워진다
const handle_ocr = async (page: string, contents: Content[] = pageContents[page] ?? []) => {
  if (!contents.length) return contents;
  const res: Content[] = await post_image("ocr", page, contents.map(({ id, pos, bubble, user, sfx }) => ({ id, pos, bubble, user, sfx })) as Content[], { ocr: settings.ocr });
  setPageContents((prev) => ({ ...prev, [page]: res }));
  return res;
}

//호출이 하나 올 때마다 TRANSLATE k/n 과 하단 막대의 그 칸을 갱신. DETECT 안 한 페이지는 건너뜀
//PaddleOCR-VL 이면 detect 전에 백엔드가 모델을 받고 띄울 때까지 기다린다 (처음 한 번만 오래 걸림)
const prepareOcr = async () => {
    if (settings.ocr !== "paddle") return;
    let s: { state: string; text: string; done: number; total: number } = await fetch(`${API}/paddle_ocr/prepare`, { method: "POST" }).then(okJson);
    while (s.state !== "ready") {
      if (s.state === "error") throw new Error(`OCR model: ${s.text}`);
      setProgress(s.state === "downloading"
        ? `Downloading ${s.text} ${s.total ? Math.floor((s.done * 100) / s.total) : 0}% (first time only)`
        : "Loading PaddleOCR-VL...");
      await new Promise((r) => setTimeout(r, 1000));
      s = await fetch(`${API}/paddle_ocr/status`).then(okJson);
    }
};

//Local 번역이면 번역 전에 백엔드가 llama.cpp·모델을 받고 띄울 때까지 기다린다 (처음 한 번만 오래 걸림)
const prepareLocal = async () => {
    if (!target.local) return;
    const post = { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model: target.model }) };
    let s: { state: string; text: string; done: number; total: number } = await fetch(`${API}/local_llm/prepare`, post).then(okJson);
    while (s.state !== "ready") {
      if (s.state === "error") throw new Error(`Local model: ${s.text}`);
      setProgress(s.state === "downloading"
        ? `Downloading ${s.text} ${s.total ? Math.floor((s.done * 100) / s.total) : 0}% (first time only)`
        : `Loading local model ${s.text}...`);
      await new Promise((r) => setTimeout(r, 1000));
      s = await fetch(`${API}/local_llm/status`).then(okJson);
    }
};

const handle_translate_pages = async (targets: string[]) => {
    const gid = (pageIndex: number, id: number) => pageIndex * 10000 + id;
    await prepareLocal();
    const detected = targets.filter((page) => pageContents[page]);
    const lines = detected.flatMap((page, pi) => pageContents[page].filter((c) => c.word).map((c) => ({ id: gid(pi, c.id), word: c.word })));

    const wanted = settings.calls === "auto" ? Math.ceil(detected.length / PAGES_PER_CALL) : settings.calls;
    const calls = Math.max(1, Math.min(wanted, lines.length));
    const size = Math.ceil(lines.length / calls);
    const parts = Array.from({ length: calls }, (_, k) => lines.slice(k * size, (k + 1) * size)).filter((p) => p.length);

    let arrived = 0;
    setCallBar(parts.map(() => false));
    setProgress(`TRANSLATE 0/${parts.length} (${modelName})`);
    //요청 하나가 실패해도 성공한 요청의 번역은 넣고, 에러는 그 뒤에 알린다
    let merged: { translations: Record<string, string>; error: unknown };
    try {
      merged = settle(await Promise.allSettled(parts.map((part, k) => translate(part).then((r) => {
        arrived++;
        setCallBar((bar) => bar && bar.map((v, j) => v || j === k));
        setProgress(`TRANSLATE ${arrived}/${parts.length} (${modelName})`);
        return r;
      }))));
    } finally {
      setCallBar(null);
    }

    const done: PageContents = {};
    for (const [pi, page] of detected.entries()) {
      done[page] = pageContents[page].map((c) => ({ ...c, translated: merged.translations[gid(pi, c.id)] ?? c.translated }));
    }
    setPageContents((prev) => ({ ...prev, ...done }));
    for (const page of detected) await ensureSfx(page, done[page]);
    if (merged.error) throw merged.error;
}

const handle_inpaint=async(inpaint_model:string=inpaintModel,page=selectedPage!, target?:Content[], base?:string)=>{
    const contents = target ?? pageContents[page];
    if (!contents || !contents.length)return;
    await prepareModels();
    const image = await post_inpaint(inpaint_model,page,contents,base);
    setInpaintedImgs((prev)=>{
        if (prev[page]?.startsWith("blob:")) URL.revokeObjectURL(prev[page]);
        return {...prev, [page]:image};
    })
    void saveErased(page, image); //기다리지 않음
}
  //효과음 렌더 갱신: 지운 이미지가 있고 번역된 의성어 상자가 있으면 백엔드에 그려 달라고 한다. 조건이 전과 같으면 건너뜀
  const ensureSfx = async (page: string, contents = pageContents[page], erased = inpaintedImgs[page]) => {
    const targets = contents ? sfxTargets(contents) : [];
    const key = erased && targets.length ? `${erased}|${targets.map((c) => `${c.id}:${c.translated}:${c.pos.join(",")}`).join("|")}` : "";
    if (sfxKeys.current[page] === key) return;
    sfxKeys.current[page] = key;
    const image = key ? await prepareModels().then(() => post_sfx(page, erased!, contents!)).catch((e) => { setProgress(`SFX render error: ${(e as Error).message}`); return undefined; }) : undefined;
    if (sfxKeys.current[page] !== key) return; //그 사이 조건이 바뀌었으면 버린다
    setSfxImgs((prev) => {
      if (prev[page]?.startsWith("blob:")) URL.revokeObjectURL(prev[page]);
      const next = { ...prev };
      if (image) next[page] = image; else delete next[page];
      return next;
    });
  };
  const handle_all = async (targets:string[]=pages)=>{
    const gid = (pageIndex:number, id:number)=> pageIndex*10000+id;
    await prepareModels();
    await prepareOcr();
    await prepareLocal();
    const per = settings.calls === "auto" ? PAGES_PER_CALL : Math.ceil(targets.length / settings.calls);

    const detected:PageContents={};
    const requests:Promise<Record<string,string>>[] = [];
    let start = 0; //아직 번역 요청 안 보낸 첫 페이지
    const send = (end:number) => {
        const lines = targets.slice(start, end).flatMap((page, k) => detected[page].filter((c) => c.word && !c.translated).map((c) => ({ id: gid(start + k, c.id), word: c.word })));
        start = end;
        if (!lines.length) return;
        const req = translate(lines);
        req.catch(()=>{});
        requests.push(req);
    };
    const reused = new Set<string>();
    for (const [page_num ,page ] of targets.entries()){
        const prev = pageContents[page];
        if (prev?.length && prev.every((c) => c.mask)) {
            detected[page] = prev;
            reused.add(page);
        } else {
            setProgress(`DETECT ${page_num+1}/${targets.length}`);
            detected[page]=await handle_ocr(page, await handle_detect(page));
        }
        if (page_num + 1 - start >= per || page_num + 1 === targets.length) send(page_num + 1);
    }
    const translating = Promise.allSettled(requests).then(settle);   //하나가 실패해도 나머지 번역은 살린다

    for (const [i, page] of targets.entries()) {
      if (reused.has(page) && inpaintedImgs[page]) continue;
      setProgress(`INPAINT ${i + 1}/${targets.length} `);
      await handle_inpaint(inpaintModel, page, detected[page]);
    }

    setProgress("Waiting for translation...");
    const { translations, error } = await translating;
    const done: PageContents = {};
    for (const [pi, page] of targets.entries()) {
      done[page] = detected[page].map((c) => ({ ...c, translated: translations[gid(pi, c.id)] ?? c.translated }));
    }
    setPageContents((prev) => ({ ...prev, ...done }));
    for (const [i, page] of targets.entries()) {
      if (!sfxTargets(done[page]).length) continue;
      setProgress(`SFX ${i + 1}/${targets.length}`);
      await ensureSfx(page, done[page]);
    }
    setView("rendered");
    if (error) throw error;
    setProgress(`Done · ${targets.length} pages`);

    
}
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [imgSize, setImgSize] = useState<[number, number]>([0, 0]);
  const removeBox = useCallback((id: number) => {
    const page = selectedPage;
    if (!page) return;
    setPageContents((prev) => ({ ...prev, [page]: (prev[page] ?? []).filter((c) => c.id !== id) }));
  }, [selectedPage]);
  const [addingBox, setAddingBox] = useState(false);
  const [addTool, setAddTool] = useState<"rect" | "pen" | "trash">("rect"); //사각형 드래그 / 펜으로 둘러 그리기(그 테두리 상자) / 상자 누르면 삭제
  const [addRect, setAddRect] = useState<[number, number, number, number] | null>(null);
  const [penPath, setPenPath] = useState<[number, number][]>([]);
  const addStart = useRef<[number, number] | null>(null);
  const toImg = (e: React.PointerEvent): [number, number] => {
    const r = canvasRef.current!.getBoundingClientRect();
    return [Math.round(((e.clientX - r.left) / r.width) * imgSize[0]), Math.round(((e.clientY - r.top) / r.height) * imgSize[1])];
  };
  const onAddDown = (e: React.PointerEvent) => {
    if (e.button !== 0 || !selectedPage) return;
    const at = toImg(e);
    if (addTool === "trash") {   //누른 자리에 있는 상자 중 가장 작은 것을 지운다
      const hit = (pageContents[selectedPage] ?? []).filter((c) => at[0] >= c.pos[0] && at[0] <= c.pos[2] && at[1] >= c.pos[1] && at[1] <= c.pos[3])
        .sort((a, b) => (a.pos[2] - a.pos[0]) * (a.pos[3] - a.pos[1]) - (b.pos[2] - b.pos[0]) * (b.pos[3] - b.pos[1]))[0];
      if (hit) removeBox(hit.id);
      return;
    }
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    addStart.current = at;
    if (addTool === "pen") setPenPath([at]);
    else setAddRect([...at, ...at] as [number, number, number, number]);
  };
  const onAddMove = (e: React.PointerEvent) => {
    if (!addStart.current) return;
    const [x, y] = toImg(e), [sx, sy] = addStart.current;
    if (addTool === "pen") setPenPath((p) => [...p, [x, y]]);
    else setAddRect([Math.min(sx, x), Math.min(sy, y), Math.max(sx, x), Math.max(sy, y)]);
  };
  const onAddUp = () => {
    const page = selectedPage;
    //펜: 그린 선을 감싸는 사각형이 상자
    const r: [number, number, number, number] | null = addTool === "pen"
      ? (penPath.length > 1 ? [Math.min(...penPath.map((q) => q[0])), Math.min(...penPath.map((q) => q[1])), Math.max(...penPath.map((q) => q[0])), Math.max(...penPath.map((q) => q[1]))] : null)
      : addRect;
    addStart.current = null;
    setAddRect(null);
    setPenPath([]);
    if (!r || !page || r[2] - r[0] < 4 || r[3] - r[1] < 4) return;
    setPageContents((prev) => {
      const cur = prev[page] ?? [];
      const id = cur.reduce((m, x) => Math.max(m, x.id), -1) + 1;
      return { ...prev, [page]: [...cur, { id, pos: r, word: "", page: 1, bubble: null, user: true }] };
    });
    setProgress("Box added · run OCR or PROCESS");
  };
  const curInpainted = selectedPage ? inpaintedImgs[selectedPage] : undefined;
  const curContents = selectedPage ? pageContents[selectedPage] : undefined;
  const curSfx = selectedPage ? sfxImgs[selectedPage] : undefined;
  //보고 있는 페이지의 효과음 번역문이 바뀌면(TEXT 패널에서 고친 것 포함) 다시 그린다
  useEffect(() => {
    if (selectedPage && curInpainted) void ensureSfx(selectedPage, curContents, curInpainted);
  }, [selectedPage, curInpainted, curContents]);
  const hasInpainted = !!curInpainted;
  const hasRendered = !!curContents?.some((c) => c.translated);
  const shownView: View = view === "rendered" && hasRendered ? "rendered" : view !== "original" && hasInpainted ? "inpainted" : "original";

  useEffect(() => {
    if (!selectedPage || !canvasRef.current) return;
    const canvas = canvasRef.current;
    let stale = false;
    (async () => {
      await ensureFont(font);
      await ensureBoxFonts(curContents ?? []);
      const withSfx = shownView === "rendered" && !!curSfx; //효과음은 백엔드가 그린 바탕에 이미 들어 있으니 캔버스로는 대사만
      const image = await loadImage(shownView === "original" ? selectedPage : (withSfx ? curSfx : curInpainted) ?? selectedPage);
      if (stale) return;
      renderPage(canvas, image, withSfx ? nonSfx(curContents ?? []) : curContents ?? [], font, shownView === "rendered");
      setImgSize([image.naturalWidth, image.naturalHeight]);
    })().catch((e) => setProgress(`Error: ${(e as Error).message}`));
    return () => {
      stale = true;
    };
  }, [selectedPage, curInpainted, curSfx, curContents, font, shownView]);

  //번호는 프로젝트 안 순서(0001_...) 그대로. 폴더 선택 미지원 브라우저면 zip 다운로드
  //EXPORT 는 항상 전체 페이지 (선택과 무관)
  const handle_export = async () => {
    const targets = pages;
    if (!targets.length) return;
    const desktop = isDesktopApp();
    const folder = desktop ? await pickFolderDesktop() : null;
    const dir = desktop ? undefined : await pickFolder();
    if ((desktop && folder === null) || dir === null) return; //취소
    await ensureFont(font);
    await ensureBoxFonts(targets.flatMap((p) => pageContents[p] ?? []));
    for (const page of targets) await ensureSfx(page); //불러온 프로젝트처럼 아직 효과음을 안 그린 페이지
    const files: ExportFile[] = [];
    let done = 0;
    await parallel(targets, 4, async (page) => {   //4장씩 동시에 (코하루와 같음)
      const i = pages.indexOf(page);
      const sfx = sfxImgs[page];
      const file = { name: pageFileName(i, names?.[i]), blob: await renderToPng(sfx ?? inpaintedImgs[page] ?? page, sfx ? nonSfx(pageContents[page] ?? []) : pageContents[page] ?? [], font) };
      if (folder) await saveToFolderDesktop(folder, file);
      else if (dir) await saveToFolder(dir, file);
      else files.push(file);
      setProgress(`EXPORT ${++done}/${targets.length}`);
    });
    if (!folder && !dir) await downloadZip(name, files);
    setProgress(`Exported ${targets.length} pages`);
  };

  //실행 모드 (PROCESS 버튼의 드롭다운으로 고름). 왼쪽 버튼을 눌러야 실행된다
  type Action = "process" | "detect" | "ocr" | "translate" | "inpaint" | "render";
  const [action, setAction] = useState<Action>("process");
  const ACTIONS: { value: Action; label: string }[] = [
    { value: "process", label: "PROCESS" },
    { value: "detect", label: "DETECT" },
    { value: "ocr", label: "OCR" },
    { value: "translate", label: "TRANSLATE" },
    { value: "inpaint", label: "INPAINT" },
    { value: "render", label: "RENDER" },
  ];
  const run_action = async () => {
    if (action === "process") return handle_all(targetPages);
    if (action === "render") return setView("rendered");
    return run_step(action);
  };

  //단계 하나만 선택한 페이지 전부에 실행
  const run_step = async (step: "detect" | "ocr" | "translate" | "inpaint") => {
    const label = { detect: "DETECT", ocr: "OCR", translate: "TRANSLATE", inpaint: "INPAINT" }[step];
    if (step !== "translate") await prepareModels();
    if (step === "ocr") await prepareOcr();
    if (step === "translate") await handle_translate_pages(targetPages);
    else for (const [i, page] of targetPages.entries()) {
      setProgress(`${label} ${i + 1}/${targetPages.length}`);
      if (step === "detect") await handle_detect(page);
      else if (step === "ocr") await handle_ocr(page);
      else await handle_inpaint(inpaintModel, page);
    }
    if (step === "inpaint") setView("inpainted");
    setProgress(`${label} done · ${targetPages.length} pages`);
  };

  //알림 (오른쪽 위 카드). 에러는 직접 닫을 때까지 남는다
  const [toasts, setToasts] = useState<Toast[]>([]);
  const toastId = useRef(0);
  const notify = (t: Omit<Toast, "id">) => setToasts((prev) => [...prev.slice(-3), { ...t, id: ++toastId.current }]);
  const closeToast = useCallback((id: number) => setToasts((prev) => prev.filter((t) => t.id !== id)), []);

  const run = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
    } catch (e) {
      const { title, description } = describeError(e);
      setProgress(`Error: ${title}`);
      notify({ kind: "error", title, description });
    }
  };

  const contents = pageContents[selectedPage!] ?? [];
  const editContent = useCallback((id: number, patch: Partial<Content>) => {
    const page = selectedPage;
    if (!page) return;
    setPageContents((prev) => ({
      ...prev,
      [page]: (prev[page] ?? []).map((c) => (c.id === id ? { ...c, ...patch } : c)),
    }));
  }, [selectedPage]);
  //상자별 폰트(c.font)로 지정된 것들도 파일을 받아 둬야 canvas 가 그 폰트로 그린다
  const ensureBoxFonts = (cs: Content[]) =>
    Promise.all([...new Set(cs.map((c) => c.font).filter(Boolean))].map((fam) => { const f = fontChoices.find((x) => x.family === fam); return f ? ensureFont(f) : undefined; }));
  //왼쪽 목록에 보여줄 페이지별 글자 상자 수 (detect 전이면 없음)
  const wordCounts = useMemo(
    () => Object.fromEntries(Object.entries(pageContents).map(([p, c]) => [p, c.length])) as Record<string, number>,
    [pageContents]
  );

  const viewLabel: Record<View, string> = { original: "Original", inpainted: "Erased", rendered: "Translated" };
  const isError = progress.startsWith("Error");

  return (
    <div className="flex h-screen flex-col bg-muted/60 text-foreground">
      {/* 상단 바: 프로젝트 이름, 보기 모드, 작업 버튼 */}
      <header className="flex h-12 shrink-0 items-center gap-2 border-b bg-background px-3">
        <Button variant="ghost" size="sm" onClick={onBack} title="Projects">←</Button>
        <button
          type="button"
          className={`flex h-8 w-8 items-center justify-center rounded-lg border text-lg leading-none transition-colors ${addingBox ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`}
          onClick={() => setAddingBox(!addingBox)}
          title="Add or remove text boxes"
        >
          ＋
        </button>
        {addingBox && ([
          ["rect", "Rectangle: drag over the text", <rect key="r" x="4" y="5" width="16" height="14" rx="1.5" strokeDasharray="4 2.5" />],
          ["pen", "Pen: draw around the text, the box wraps the stroke", <g key="p"><path d="M18.4 2.6a2.1 2.1 0 0 1 3 3L11 16l-4 1 1-4Z" /><path d="M3 21c3 0 5-2 5-5" /></g>],
          ["trash", "Trash: click a box to remove it", <g key="t"><path d="M3 6h18" /><path d="M8 6V4h8v2" /><path d="M19 6l-1 14H6L5 6" /><path d="M10 11v6M14 11v6" /></g>],
        ] as const).map(([tool, tip, icon]) => (
          <button key={tool} type="button" className={`flex h-8 w-8 items-center justify-center rounded-lg border transition-colors ${addTool === tool ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`} onClick={() => setAddTool(tool)} title={tip}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">{icon}</svg>
          </button>
        ))}

        <div className="ml-1 flex overflow-hidden rounded-lg border bg-background text-xs">
          {(["original", "inpainted", "rendered"] as const).map((v) => (
            <button
              key={v}
              type="button"
              className={`px-3 py-1.5 transition-colors ${shownView === v ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`}
              onClick={() => setView(v)}
            >
              {viewLabel[v]}
            </button>
          ))}
        </div>

        <div className="ml-auto flex flex-wrap items-center justify-end gap-1.5">
          <RepeatButton pages={pages} selectedPage={selectedPage} onGo={goPage} />
          <span className="mx-1 h-5 w-px bg-border" />
          <SplitButton
            value={action}
            options={ACTIONS}
            onSelect={setAction}
            onRun={() => run(run_action)}
            suffix={targetPages.length > 1 ? ` (${targetPages.length})` : ""}
          />
          <Button variant="secondary" size="sm" onClick={() => run(() => handle_all())}>PROCESS ALL</Button>
          <Button variant="outline" size="sm" onClick={() => run(handle_export)}>EXPORT</Button>
        </div>
      </header>
      <div className="flex min-h-0 flex-1">
        {/* 접힌 PAGES: 얇은 띠 + 펼치기 */}
        {!leftOpen && (
          <button
            className="flex w-7 shrink-0 flex-col items-center gap-2 border-r bg-background pt-2 text-muted-foreground hover:bg-muted"
            onClick={() => setLeftOpen(true)}
            title="Expand PAGES"
          >
            <span className="text-[10px]">▶</span>
            <span className="text-[10px] [writing-mode:vertical-rl]">PAGES</span>
          </button>
        )}

        <Group className="flex min-h-0 flex-1">
          {/* 왼쪽: 페이지 목록 */}
          {leftOpen && (
            <Panel defaultSize="14%" minSize="10%" className="flex flex-col border-r bg-background">
              <div className="flex h-9 shrink-0 items-center gap-2 border-b px-3 text-[11px] font-semibold tracking-wide text-muted-foreground">
                <span>PAGES</span>
                <span className="rounded-full bg-muted px-2 py-0.5 text-[10px]">{pages.length}</span>
                {selectedPages.length > 1 && <span className="text-[10px] text-accent-foreground">{selectedPages.length} selected</span>}
                <button className="ml-auto rounded px-1 text-[10px] hover:bg-muted" onClick={() => setLeftOpen(false)} title="Collapse">◀</button>
              </div>
              <PageList pages={pages} counts={wordCounts} selectedPage={selectedPage} selectedPages={selectedPages} onClick={clickPage} />
            </Panel>
          )}
          {leftOpen && <Separator className="w-px bg-border transition-colors hover:bg-primary/50" />}

          {/* 가운데: 페이지 */}
          <Panel className="min-w-0 overflow-hidden">
           <div ref={scrollRef} className={`relative h-full overflow-auto ${fullscreen ? "bg-black" : "bg-muted/60"}`}>
            {/* 위 가운데 떠 있는 보기 버튼: 전체화면 / 한 화면에 맞춤 / 폭에 맞춤 */}
            <div className="sticky top-2 z-10 flex justify-center">
              <div className="flex overflow-hidden rounded-lg border bg-background/90 text-xs shadow-sm backdrop-blur">
                <button className={`px-2.5 py-1 hover:bg-muted ${fullscreen ? "bg-primary text-primary-foreground" : ""}`} onClick={toggleFullscreen} title="Fullscreen">⛶</button>
                <button className={`border-l px-2.5 py-1 hover:bg-muted ${fit === "page" ? "bg-primary text-primary-foreground" : ""}`} onClick={() => setFit("page")} title="Fit page">↔ fit</button>
                <button className={`border-l px-2.5 py-1 hover:bg-muted ${fit === "width" ? "bg-primary text-primary-foreground" : ""}`} onClick={() => setFit("width")} title="Fit width">↕ fit</button>
                <button className="border-l px-2.5 py-1 hover:bg-muted disabled:opacity-40" disabled={pageIndex <= 0} onClick={() => stepPage(-1)} title="Previous page (←)">‹ prev</button>
                <button className="border-l px-2.5 py-1 hover:bg-muted disabled:opacity-40" disabled={pageIndex < 0 || pageIndex >= pages.length - 1} onClick={() => stepPage(1)} title="Next page (→)">next ›</button>
              </div>
            </div>
            {/* 흰 카드는 그림 크기를 그대로 따라간다 (카드에 높이 제한을 주면 그림만 삐져나옴). 그림 최대 높이 = 화면 - 상단바/하단줄/여백/카드 패딩 */}
            <div className={`flex justify-center px-8 pb-8 pt-4 ${fit === "page" ? "h-[calc(100%-2.25rem)] items-center" : "min-h-full items-start"}`}>
              <div className={`inline-block max-w-full rounded-md p-2 ${fullscreen ? "bg-black" : "bg-background shadow-[0_8px_30px_rgba(0,0,0,0.12)] ring-1 ring-black/5"}`}>
                <div className="relative inline-block overflow-visible">
                  <canvas
                    ref={canvasRef}
                    className={`block rounded-sm ${
                      fit === "page" ? `h-auto w-auto max-w-full ${fullscreen ? "max-h-[calc(100vh-5.5rem)]" : "max-h-[calc(100vh-10.5rem)]"}` : "h-auto max-w-full"
                    }`}
                  />
                  {imgSize[0] > 0 && (curContents ?? []).some((c) => c.user && !c.word) && (
                    <svg className="pointer-events-none absolute inset-0 z-20 h-full w-full overflow-visible" viewBox={`0 0 ${imgSize[0]} ${imgSize[1]}`} preserveAspectRatio="none">
                      {(curContents ?? []).filter((c) => c.user && !c.word).map((c) => (
                        <rect key={c.id} x={c.pos[0]} y={c.pos[1]} width={c.pos[2] - c.pos[0]} height={c.pos[3] - c.pos[1]} fill="rgba(59,130,246,0.12)" stroke="#3b82f6" strokeWidth={2} strokeDasharray="6 4" vectorEffect="non-scaling-stroke" />
                      ))}
                    </svg>
                  )}
                  {addingBox && imgSize[0] > 0 && (
                    <div className={`absolute inset-0 z-30 touch-none ${addTool === "trash" ? "cursor-pointer" : "cursor-crosshair"}`} onPointerDown={onAddDown} onPointerMove={onAddMove} onPointerUp={onAddUp} onPointerCancel={onAddUp}>
                      <svg className="pointer-events-none h-full w-full overflow-visible" viewBox={`0 0 ${imgSize[0]} ${imgSize[1]}`} preserveAspectRatio="none">
                        {addTool === "trash" && (curContents ?? []).map((c) => (
                          <rect key={c.id} x={c.pos[0]} y={c.pos[1]} width={c.pos[2] - c.pos[0]} height={c.pos[3] - c.pos[1]} fill="rgba(239,68,68,0.10)" stroke="#ef4444" strokeWidth={2} vectorEffect="non-scaling-stroke" />
                        ))}
                        {addRect && <rect x={addRect[0]} y={addRect[1]} width={addRect[2] - addRect[0]} height={addRect[3] - addRect[1]} fill="rgba(59,130,246,0.15)" stroke="#3b82f6" strokeWidth={2} strokeDasharray="6 4" vectorEffect="non-scaling-stroke" />}
                        {penPath.length > 1 && <polyline points={penPath.map((q) => q.join(",")).join(" ")} fill="none" stroke="#3b82f6" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />}
                      </svg>
                    </div>
                  )}
                </div>
              </div>
            </div>
           </div>
          </Panel>

          {rightOpen && <Separator className="w-px bg-border transition-colors hover:bg-primary/50" />}
          {/* 오른쪽: 글자 목록 + 설정 */}
          {rightOpen && (
            <Panel defaultSize="20%" minSize="14%" className="flex flex-col border-l bg-background">
              <div className="min-h-0 flex-1 overflow-y-auto">
                <Text contents={contents} fonts={fontChoices} selectedArea={selectedArea} onSelect={setSelectedArea} onEdit={editContent} onRemove={removeBox} onCollapse={() => setRightOpen(false)} />
              </div>
              {/* 오른쪽 아래: 설정 창 여는 버튼 */}
              <div className="shrink-0 border-t bg-muted/40 p-2">
                <Button variant="outline" size="sm" className="w-full justify-start gap-2" onClick={() => setSettingsOpen(true)}>
                  <span>⚙</span>
                  <span>SETTINGS</span>
                </Button>
              </div>
            </Panel>
          )}
        </Group>

        {/* 접힌 TEXT: 얇은 띠 + 펼치기 */}
        {!rightOpen && (
          <button
            className="flex w-7 shrink-0 flex-col items-center gap-2 border-l bg-background pt-2 text-muted-foreground hover:bg-muted"
            onClick={() => setRightOpen(true)}
            title="Expand TEXT"
          >
            <span className="text-[10px]">◀</span>
            <span className="text-[10px] [writing-mode:vertical-rl]">TEXT</span>
          </button>
        )}
      </div>

      <SettingsDialog
        open={settingsOpen}
        settings={settings}
        fonts={fontChoices}
        font={font}
        onFont={set_font}
        onChange={setSettings}
        onClose={() => setSettingsOpen(false)}
      />

      <Toasts items={toasts} onClose={closeToast} />

      {setup && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="w-[440px] rounded-lg border bg-background p-6 shadow-xl">
            <div className="text-sm font-medium">{setup.state === "error" ? "Model setup failed" : "Preparing AI models"}</div>
            <div className="mt-2 text-sm text-muted-foreground">{setup.text}{setup.pct !== null && setup.state !== "error" ? `  ${setup.pct}%` : ""}</div>
            {setup.state !== "error" && (
              <div className="mt-3 h-2 w-full overflow-hidden rounded bg-muted">
                <div className={`h-full bg-primary transition-all ${setup.pct === null ? "w-1/3 animate-pulse" : ""}`} style={setup.pct === null ? undefined : { width: `${setup.pct}%` }} />
              </div>
            )}
            <div className="mt-2 text-[11px] text-muted-foreground">First time only. Downloads the detection and OCR models (about 0.8 GB).</div>
            {setup.state === "error" && <Button className="mt-3" size="sm" onClick={() => setSetup(null)}>Close</Button>}
          </div>
        </div>
      )}

      {/* 하단 상태 줄 */}
      <footer className="flex h-7 shrink-0 items-center gap-3 border-t bg-background px-3 text-[11px] text-muted-foreground">
        <span>{contents.length} texts</span>
        <span>·</span>
        <span>{viewLabel[shownView]} view</span>
        <span>·</span>
        <span>{settings.source} → {settings.target}</span>
        {/* TRANSLATE 진행 막대: 칸 = API 호출, 응답이 온 칸만 색칠 */}
        {callBar && (
          <div className="ml-auto flex h-1.5 w-40 shrink-0 gap-0.5" title={`${callBar.filter(Boolean).length}/${callBar.length}`}>
            {callBar.map((done, k) => (
              <div key={k} className={`flex-1 rounded-sm ${done ? "bg-primary" : "bg-border"}`} />
            ))}
          </div>
        )}
        {progress && (
          <span className={`${callBar ? "" : "ml-auto "}rounded-full px-2.5 py-0.5 ${isError ? "bg-destructive/10 text-destructive" : "bg-accent text-accent-foreground"}`}>
            {progress}
          </span>
        )}
      </footer>
    </div>
  );
}
