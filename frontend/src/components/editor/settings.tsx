import { memo, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { API } from "@/api";
import { FontPicker } from "./fontpicker";
import { UI_LANGS, defaultUi, langName, translator, type UiLang } from "./i18n";
import type { FontChoice } from "../../Project";

//설정 창 (오른쪽 아래 ⚙ SETTINGS 버튼으로 연다). 코하루처럼 왼쪽에 영역 탭, 오른쪽에 그 영역의 설정
type Lang = string; //Gemini 에 그대로 넘기는 영어 언어명

//localModel 은 앱이 직접 받아 이 PC 에서 돌리는 모델 (백엔드 Process/local_llm.py)
//키들은 설정과 따로 localStorage 에 저장한다
export type Provider = "gemini" | "chatgpt" | "claude" | "openai" | "local";
export type OcrModel = "paddle" | "hayai";
export type Effort = "low" | "medium" | "high";
export const EFFORTS: Effort[] = ["low", "medium", "high"];
export type AppSettings = {
  source: Lang; target: Lang; calls: "auto" | number; ocr: OcrModel; ui: UiLang;   //ui: 설정 창의 화면 언어
  provider: Provider; model: string; model2: string; gptModel: string; claudeModel: string; claudeEffort: Effort; openaiUrl: string; openaiModel: string; localModel: string;
  apiKey: string; gptKey: string; claudeKey: string; openaiKey: string;
};

export const PROVIDERS: Record<Provider, { label: string; url: string; models: string[]; keyUrl: string }> = {
  gemini: { label: "Gemini", url: "", models: ["gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.8-flash", "gemini-3.5-flash-lite"], keyUrl: "https://aistudio.google.com/apikey" },
  chatgpt: { label: "ChatGPT", url: "https://api.openai.com/v1", models: ["gpt-6-luna", "gpt-6-sol", "gpt-6-astra"], keyUrl: "https://platform.openai.com/api-keys" },
  claude: { label: "Claude", url: "", models: ["claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5"], keyUrl: "https://platform.claude.com/settings/keys" },
  openai: { label: "OpenAI", url: "", models: [], keyUrl: "" },
  local: { label: "Local", url: "", models: [], keyUrl: "" },
};
//provider 별로 쓰는 설정 칸
const FIELDS = {
  gemini: { model: "model", key: "apiKey" },
  chatgpt: { model: "gptModel", key: "gptKey" },
  claude: { model: "claudeModel", key: "claudeKey" },
} as const;

export const LOCAL_MODELS: { id: string; name: string; size: string }[] = [
  { id: "qwen3.5-9b", name: "Qwen 3.5 9B", size: "5.7 GB" },
  { id: "qwen3.5-9b-uncensored", name: "Qwen 3.5 9B Uncensored", size: "5.6 GB" },
  { id: "qwen3.6-27b-uncensored", name: "Qwen 3.6 27B Uncensored", size: "15 GB" },
  { id: "qwen3.6-35b-a3b-uncensored", name: "Qwen 3.6 35B A3B Uncensored", size: "23 GB" },
  { id: "vntl-llama3-8b", name: "VNTL Llama 3 8B v2", size: "5.7 GB" },
  { id: "gemma4-e2b-it", name: "Gemma 4 E2B Instruct", size: "2.6 GB" },
  { id: "gemma4-e4b-it", name: "Gemma 4 E4B Instruct", size: "4.2 GB" },
  { id: "gemma4-12b-it", name: "Gemma 4 12B Instruct", size: "6.7 GB" },
  { id: "gemma4-26b-a4b-it", name: "Gemma 4 26B A4B Instruct", size: "14 GB" },
  { id: "gemma4-31b-it", name: "Gemma 4 31B Instruct", size: "17 GB" },
];

export const DEFAULT_SETTINGS: AppSettings = {
  source: "Japanese", target: "Korean", calls: "auto", ocr: "hayai", ui: defaultUi(),
  provider: "gemini", model: "gemini-3.5-flash-lite", model2: "gemini-3.6-flash", gptModel: "gpt-6-luna", claudeModel: "claude-sonnet-5-5", claudeEffort: "medium", openaiUrl: "", openaiModel: "", localModel: "gemma4-12b-it",
  apiKey: "", gptKey: "", claudeKey: "", openaiKey: "",
};

export const translateTarget = (s: AppSettings): { model: string; model2?: string; baseUrl?: string; local?: boolean; provider?: "claude"; effort?: Effort; headers: Record<string, string> } => {
  const key = (k: string): Record<string, string> => (k ? { "X-Api-Key": k } : {});
  if (s.provider === "chatgpt") return { model: s.gptModel, baseUrl: PROVIDERS.chatgpt.url, headers: key(s.gptKey) };
  if (s.provider === "claude") return { model: s.claudeModel, provider: "claude", effort: s.claudeEffort, headers: key(s.claudeKey) };
  if (s.provider === "openai") return { model: s.openaiModel, baseUrl: s.openaiUrl, headers: key(s.openaiKey) };
  if (s.provider === "local") return { model: s.localModel, local: true, headers: {} };
  return { model: s.model, model2: s.model2, headers: key(s.apiKey) };   //Gemini: model 이 실패(429·5xx)하면 model2 로
};
export const PAGES_PER_CALL = 30;
const CALL_PRESETS = ["auto", 1, 2, 5] as const;

//설정은 브라우저 localStorage 에 남긴다 (앱을 껐다 켜도 유지). API 키는 따로 저장
const SETTINGS_STORAGE = "manga_settings";
export const loadSettings = (): Partial<AppSettings> & { fontFamily?: string; sfxFontFamily?: string } => {
  try { return JSON.parse(localStorage.getItem(SETTINGS_STORAGE) ?? "{}"); } catch { return {}; }
};
export const saveSettings = (s: AppSettings, fontFamily: string, sfxFontFamily: string) => {
  try {
    const { apiKey: _k, gptKey: _g, claudeKey: _c, openaiKey: _o, ...rest } = s;
    localStorage.setItem(SETTINGS_STORAGE, JSON.stringify({ ...rest, fontFamily, sfxFontFamily }));
  } catch { /* 저장 못 해도 동작엔 지장 없음 */ }
};

export const loadKey = (p: Provider) => { try { return localStorage.getItem(`${p}_api_key`) ?? ""; } catch { return ""; } };
const saveKey = (p: Provider, k: string) => { try { k ? localStorage.setItem(`${p}_api_key`, k) : localStorage.removeItem(`${p}_api_key`); } catch { /* 저장 못 해도 동작엔 지장 없음 */ } };

//OK 버튼: 키를 백엔드로 보내 .env 에 저장 (앱을 껐다 켜도 서버가 이 키를 쓴다)
const postApiKey = async (k: string) => {
  const body = new FormData();
  body.append("api_key", k);
  const r = await fetch(`${API}/api_key`, { method: "POST", body });
  if (!r.ok) throw new Error(`${r.status}`);
};

//Show/Hide 버튼용 눈 아이콘 (off = 사선)
function EyeIcon({ off }: { off: boolean }) {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" />
      <circle cx="12" cy="12" r="3" />
      {off && <line x1="3" y1="3" x2="21" y2="21" />}
    </svg>
  );
}

//Gemini 는 언어를 가리지 않으니 넉넉히. 값 = 영어 이름 (표시는 화면 언어로, i18n.langName)
const LANGS: Lang[] = [
  "Japanese", "Korean", "English", "Chinese (Simplified)", "Chinese (Traditional)",
  "Spanish", "French", "German", "Italian", "Portuguese", "Russian", "Ukrainian", "Polish", "Dutch",
  "Swedish", "Norwegian", "Danish", "Finnish", "Czech", "Hungarian", "Romanian", "Greek", "Turkish",
  "Arabic", "Hebrew", "Persian", "Hindi", "Bengali", "Urdu", "Tamil",
  "Vietnamese", "Thai", "Indonesian", "Malay", "Filipino", "Burmese", "Khmer", "Mongolian",
];

type Tab = "language" | "models";
const TABS: { id: Tab; label: string }[] = [   //label 은 영어 (그릴 때 화면 언어로 바꾼다)
  { id: "language", label: "Language" },
  { id: "models", label: "Models" },
];

const selectCls = "h-8 rounded-lg border bg-background px-2 text-sm outline-none hover:bg-muted focus:border-primary focus:ring-2 focus:ring-primary/20";

//영역 안의 한 묶음: 제목 + 설명 + 내용
function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="border-b py-4 first:pt-0 last:border-b-0">
      <h3 className="text-sm font-semibold">{title}</h3>
      {hint && <p className="mt-0.5 text-[11px] text-muted-foreground">{hint}</p>}
      <div className="mt-3">{children}</div>
    </section>
  );
}

//한 줄 설정: 왼쪽 라벨, 오른쪽 입력
function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex items-center justify-between gap-4 py-1.5 text-sm">
      <span>{label}</span>
      <span className="flex min-w-0 items-center gap-1">{children}</span>
    </label>
  );
}

//API 키 입력칸 + Show/Hide
function KeyInput({ value, placeholder, onChange, t }: { value: string; placeholder: string; onChange: (k: string) => void; t: (s: string) => string }) {
  const [show, setShow] = useState(false);
  return (
    <div className="flex items-center gap-1">
      <input
        className={`${selectCls} w-64 min-w-0 font-mono`}
        type={show ? "text" : "password"}
        placeholder={placeholder}
        autoComplete="off"
        spellCheck={false}
        value={value}
        onChange={(e) => onChange(e.target.value.trim())}
      />
      <button className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border hover:bg-muted" onClick={() => setShow(!show)} title={t(show ? "Hide" : "Show")}>
        <EyeIcon off={show} />
      </button>
    </div>
  );
}

export const SettingsDialog = memo(function SettingsDialog({
  open,
  settings,
  fonts,
  font,
  onFont,
  sfxFonts,
  sfxFont,
  onSfxFont,
  onChange,
  needKey,
  onClose,
}: {
  open: boolean;
  settings: AppSettings;
  fonts: FontChoice[]; //대사 글꼴 선택지
  font: FontChoice;
  onFont: (f: FontChoice) => void;
  sfxFonts: FontChoice[]; //효과음 글꼴 선택지 (백엔드가 가진 폰트만. 효과음은 백엔드가 그린다)
  sfxFont: FontChoice;
  onSfxFont: (f: FontChoice) => void;
  onChange: (s: AppSettings) => void;
  needKey?: boolean; //번역이 API 키 때문에 실패해서 열림 → Models 탭, 키 칸 옆 빛나는 표시와 경고
  onClose: () => void;
}) {
  const [tab, setTab] = useState<Tab>("language");
  useEffect(() => { if (open && needKey) setTab("models"); }, [open, needKey]);
  const [customCalls, setCustomCalls] = useState(typeof settings.calls === "number" && !CALL_PRESETS.includes(settings.calls as never));
  const [customStr, setCustomStr] = useState(typeof settings.calls === "number" ? String(settings.calls) : "3");

  //Esc 로 닫기
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  const set = (patch: Partial<AppSettings>) => onChange({ ...settings, ...patch });
  const t = translator(settings.ui);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onMouseDown={onClose}>
      <div className="flex h-[30rem] w-[42rem] max-w-[calc(100vw-2rem)] overflow-hidden rounded-2xl border bg-background shadow-2xl" onMouseDown={(e) => e.stopPropagation()}>
        {/* 왼쪽: 영역 탭 */}
        <aside className="flex w-40 shrink-0 flex-col border-r bg-muted/40 p-2">
          <div className="px-2 py-2 text-[11px] font-semibold tracking-wide text-muted-foreground">{t("SETTINGS")}</div>
          {TABS.map((tb) => (
            <button
              key={tb.id}
              className={`rounded-lg px-3 py-2 text-left text-sm transition-colors ${tab === tb.id ? "bg-accent font-medium text-accent-foreground" : "hover:bg-muted"}`}
              onClick={() => setTab(tb.id)}
            >
              {t(tb.label)}
            </button>
          ))}
          <div className="mt-auto px-2 pb-1 text-[10px] text-muted-foreground">{t("Esc to close")}</div>
        </aside>

        {/* 오른쪽: 내용 */}
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex h-11 shrink-0 items-center justify-between border-b px-5">
            <h2 className="text-sm font-semibold">{t(TABS.find((tb) => tb.id === tab)!.label)}</h2>
            <button className="rounded px-1.5 text-muted-foreground hover:bg-muted" onClick={onClose} title={t("Close")}>✕</button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-5">
            {tab === "language" && (
              <Section title={t("Interface language")} hint={t("Language of this settings window.")}>
                <select className={`${selectCls} w-64`} value={settings.ui} onChange={(e) => set({ ui: e.target.value as UiLang })}>
                  {UI_LANGS.map((l) => <option key={l.id} value={l.id}>{l.label}</option>)}
                </select>
              </Section>
            )}
            {tab === "language" && (
              <Section title={t("Translation direction")}>
                <div className="flex items-end gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="mb-1 text-[11px] font-medium text-muted-foreground">{t("Source")}</p>
                    <select className={`${selectCls} w-full`} value={settings.source} onChange={(e) => set({ source: e.target.value })}>
                      {LANGS.map((l) => <option key={l} value={l}>{langName(settings.ui, l)}</option>)}
                    </select>
                  </div>
                  <button
                    className="h-8 shrink-0 rounded-lg border px-2 text-xs hover:bg-muted"
                    onClick={() => set({ source: settings.target, target: settings.source })}
                    title={t("Swap")}
                  >
                    ⇄
                  </button>
                  <div className="min-w-0 flex-1">
                    <p className="mb-1 text-[11px] font-medium text-muted-foreground">{t("Target")}</p>
                    <select className={`${selectCls} w-full`} value={settings.target} onChange={(e) => set({ target: e.target.value })}>
                      {LANGS.map((l) => <option key={l} value={l}>{langName(settings.ui, l)}</option>)}
                    </select>
                  </div>
                </div>
              </Section>
            )}
            {tab === "language" && (
              <Section title={t("Font")} hint={t("Fonts used to draw the translated text. Dialogue and sound effects are set separately.")}>
                <p className="mb-1 text-[11px] font-medium text-muted-foreground">{t("Dialogue")}</p>
                <FontPicker fonts={fonts} value={font} onChange={onFont} title={t("Choose a font")} inline />
                <p className="mb-1 mt-3 text-[11px] font-medium text-muted-foreground">{t("Sound effects")}</p>
                <FontPicker fonts={sfxFonts} value={sfxFont} onChange={onSfxFont} title={t("Choose a font")} inline />
              </Section>
            )}

            {tab === "models" && (
              <>
                <Section title={t("OCR model")}>
                  <select className={`${selectCls} w-64`} value={settings.ocr} onChange={(e) => set({ ocr: e.target.value as OcrModel })}>
                    <option value="paddle">PaddleOCR</option>
                    <option value="hayai">HAYAI OCR</option>
                  </select>
                </Section>
                <Section title={t("Translation model")}>
                  <Row label={t("Provider")}>
                    <select className={`${selectCls} w-64`} value={settings.provider} onChange={(e) => set({ provider: e.target.value as Provider })}>
                      {(Object.keys(PROVIDERS) as Provider[]).map((p) => <option key={p} value={p}>{PROVIDERS[p].label}</option>)}
                    </select>
                  </Row>
                  {settings.provider === "local" ? (
                    <>
                      <Row label={t("Model")}>
                        <select className={`${selectCls} w-64`} value={settings.localModel} onChange={(e) => set({ localModel: e.target.value })}>
                          {LOCAL_MODELS.map((m) => <option key={m.id} value={m.id}>{m.name}{m.size && ` (${m.size})`}</option>)}
                        </select>
                      </Row>
                      <p className="mt-1.5 text-[11px] text-muted-foreground">
                        {t("Runs on this PC's GPU with llama.cpp. The model is downloaded the first time you translate (several GB) and kept in the app folder.")}
                      </p>
                    </>
                  ) : settings.provider === "openai" ? (
                    <>
                      <Row label={t("Base URL")}>
                        <input className={`${selectCls} w-64 min-w-0 font-mono`} placeholder="http://localhost:11434/v1" spellCheck={false} value={settings.openaiUrl} onChange={(e) => set({ openaiUrl: e.target.value.trim() })} />
                      </Row>
                      <Row label={t("Model")}>
                        <input className={`${selectCls} w-64 min-w-0 font-mono`} placeholder="e.g. qwen3:8b" spellCheck={false} value={settings.openaiModel} onChange={(e) => set({ openaiModel: e.target.value.trim() })} />
                      </Row>
                      <p className="mb-1 mt-3 text-[11px] font-medium text-muted-foreground">{t("API key")}</p>
                      <KeyInput t={t} value={settings.openaiKey} placeholder={t("optional")} onChange={(k) => { saveKey("openai", k); set({ openaiKey: k }); }} />
                      <p className="mt-1.5 text-[11px] text-muted-foreground">
                        {t("Any OpenAI-compatible /chat/completions API: a server on this PC (Ollama, LM Studio, llama.cpp) or a cloud API. Leave the key empty if not needed.")}
                      </p>
                    </>
                  ) : (() => {
                    const p = settings.provider;
                    const f = FIELDS[p];
                    return (
                      <>
                        {PROVIDERS[p].url && (
                          <Row label={t("Base URL")}>
                            <input className={`${selectCls} w-64 min-w-0 font-mono opacity-60`} value={PROVIDERS[p].url} readOnly />
                          </Row>
                        )}
                        <Row label={t(p === "gemini" ? "Main model" : "Model")}>
                          <select className={`${selectCls} w-64`} value={settings[f.model]} onChange={(e) => set({ [f.model]: e.target.value })}>
                            {PROVIDERS[p].models.map((m) => <option key={m} value={m}>{m}</option>)}
                          </select>
                        </Row>
                        {p === "gemini" && (
                          <Row label={t("Sub model")}>
                            <select className={`${selectCls} w-64`} value={settings.model2} onChange={(e) => set({ model2: e.target.value })}>
                              {PROVIDERS.gemini.models.map((m) => <option key={m} value={m}>{m}</option>)}
                            </select>
                          </Row>
                        )}
                        {p === "gemini" && (
                          <p className="text-[11px] text-muted-foreground">{t("The main model is tried first on every request. If it fails (limit reached or overloaded), that request uses the sub model.")}</p>
                        )}
                        {p === "claude" && (
                          <>
                            <Row label={t("Effort")}>
                              <select className={`${selectCls} w-64`} value={settings.claudeEffort} onChange={(e) => set({ claudeEffort: e.target.value as Effort })}>
                                {EFFORTS.map((m) => <option key={m} value={m}>{t(m)}</option>)}
                              </select>
                            </Row>
                            <p className="text-[11px] text-muted-foreground">{t("How much the model thinks before answering. Higher is slower and costs more output tokens.")}</p>
                          </>
                        )}
                        <p className="mb-1 mt-3 flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
                          {t("API key")}
                          {needKey && !settings[f.key] && <span className="h-2 w-2 animate-pulse rounded-full bg-red-500 shadow-[0_0_6px_2px_rgba(239,68,68,0.7)]" />}
                        </p>
                        <KeyInput t={t} value={settings[f.key]} placeholder={p === "gemini" ? "AIza..." : p === "claude" ? "sk-ant-..." : "sk-..."} onChange={(k) => { saveKey(p, k); set({ [f.key]: k }); }} />
                        {needKey && !settings[f.key] && (
                          <p className="mt-1.5 text-[11px] font-medium text-red-500">{t("{name} API key is required. Enter it above to translate.", { name: PROVIDERS[p].label })}</p>
                        )}
                        <p className="mt-1.5 text-[11px] text-muted-foreground">
                          {t("Stored only in this browser, sent to your local backend.")}{p === "gemini" && t(" Empty = server default key.")}{t(" Get one at ")}
                          <a className="underline" href={PROVIDERS[p].keyUrl} target="_blank" rel="noreferrer">{PROVIDERS[p].keyUrl.replace("https://", "")}</a>
                        </p>
                      </>
                    );
                  })()}
                  <Row label={t("API calls")}>
                    <select
                      className={selectCls}
                      value={customCalls ? "custom" : String(settings.calls)}
                      onChange={(e) => {
                        const v = e.target.value;
                        if (v === "custom") { setCustomCalls(true); set({ calls: Math.max(1, Number(customStr) || 1) }); }
                        else { setCustomCalls(false); set({ calls: v === "auto" ? "auto" : Number(v) }); }
                      }}
                    >
                      {CALL_PRESETS.map((c) => <option key={String(c)} value={String(c)}>{c === "auto" ? t("auto") : String(c)}</option>)}
                      <option value="custom">{t("custom")}</option>
                    </select>
                    {customCalls && (
                      <input
                        className={`${selectCls} w-16 text-right`}
                        type="number"
                        min={1}
                        value={customStr}
                        onChange={(e) => { setCustomStr(e.target.value); const n = Number(e.target.value); if (n >= 1) set({ calls: Math.round(n) }); }}
                      />
                    )}
                  </Row>
                  <p className="text-[11px] text-muted-foreground">
                    {t("How many API calls PROCESS ALL uses. 1 = send all text in one call, 2 = split it into two calls. auto = 1 call per {n} pages.", { n: PAGES_PER_CALL })}
                  </p>
                </Section>
              </>
            )}
          </div>
          <div className="flex h-12 shrink-0 items-center justify-end border-t px-5">
            <Button size="sm" onClick={() => { if (settings.apiKey) postApiKey(settings.apiKey).catch(() => {}); onClose(); }}>{t("OK")}</Button>
          </div>
        </div>
      </div>
    </div>
  );
});
