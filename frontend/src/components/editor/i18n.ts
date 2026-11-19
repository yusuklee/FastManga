//설정 창 글의 번역. 영어 문장이 열쇠이고 값은 [한국어, 중국어]. 여기 없는 문장은 영어 그대로 나온다
export type UiLang = "en" | "ko" | "zh";
export const UI_LANGS: { id: UiLang; label: string }[] = [
  { id: "ko", label: "한국어" },
  { id: "en", label: "English" },
  { id: "zh", label: "中文" },
];
//처음 켰을 때의 화면 언어: 윈도우 언어를 따른다
export const defaultUi = (): UiLang => {
  const l = navigator.language.toLowerCase();
  return l.startsWith("ko") ? "ko" : l.startsWith("zh") ? "zh" : "en";
};

const TEXT: Record<string, [ko: string, zh: string]> = {
  "SETTINGS": ["설정", "设置"],
  "Language": ["언어", "语言"],
  "Models": ["모델", "模型"],
  "Esc to close": ["Esc 로 닫기", "按 Esc 关闭"],
  "Close": ["닫기", "关闭"],
  "OK": ["확인", "确定"],
  "Interface language": ["화면 언어", "界面语言"],
  "Language of this settings window.": ["이 설정 창에 쓰는 언어입니다.", "此设置窗口使用的语言。"],
  "Translation direction": ["번역 방향", "翻译方向"],
  "Source": ["원문", "原文"],
  "Target": ["번역", "译文"],
  "Swap": ["서로 바꾸기", "互换"],
  "Font": ["폰트", "字体"],
  "Fonts used to draw the translated text. Dialogue and sound effects are set separately.": ["번역문을 그릴 때 쓰는 폰트입니다. 대사와 효과음을 따로 정합니다.", "绘制译文时使用的字体。对白和拟声词分别设置。"],
  "Dialogue": ["대사", "对白"],
  "Sound effects": ["효과음", "拟声词"],
  "Choose a font": ["폰트 고르기", "选择字体"],
  "OCR model": ["OCR 모델", "OCR 模型"],
  "Translation model": ["번역 모델", "翻译模型"],
  "Provider": ["제공자", "服务商"],
  "Model": ["모델", "模型"],
  "Main model": ["주 모델", "主模型"],
  "Sub model": ["보조 모델", "备用模型"],
  "Base URL": ["기본 URL", "接口地址"],
  "API key": ["API 키", "API 密钥"],
  "Effort": ["생각 수준", "思考强度"],
  "low": ["낮음", "低"],
  "medium": ["보통", "中"],
  "high": ["높음", "高"],
  "API calls": ["API 요청 수", "API 调用次数"],
  "auto": ["자동", "自动"],
  "custom": ["직접 입력", "自定义"],
  "optional": ["선택", "可选"],
  "Hide": ["숨기기", "隐藏"],
  "Show": ["보기", "显示"],
  "Runs on this PC's GPU with llama.cpp. The model is downloaded the first time you translate (several GB) and kept in the app folder.": [
    "이 PC 의 GPU 에서 llama.cpp 로 돌립니다. 모델은 처음 번역할 때 내려받아(수 GB) 앱 폴더에 보관합니다.",
    "使用 llama.cpp 在本机 GPU 上运行。首次翻译时会下载模型（数 GB），并保存在应用文件夹中。",
  ],
  "Any OpenAI-compatible /chat/completions API: a server on this PC (Ollama, LM Studio, llama.cpp) or a cloud API. Leave the key empty if not needed.": [
    "OpenAI 호환 /chat/completions API 라면 무엇이든 됩니다. 이 PC 의 서버(Ollama, LM Studio, llama.cpp)나 클라우드 API 를 쓸 수 있습니다. 키가 필요 없으면 비워 두세요.",
    "任何兼容 OpenAI 的 /chat/completions API 均可：本机服务（Ollama、LM Studio、llama.cpp）或云端 API。不需要密钥时请留空。",
  ],
  "The main model is tried first on every request. If it fails (limit reached or overloaded), that request uses the sub model.": [
    "요청마다 주 모델을 먼저 씁니다. 실패하면(한도 초과나 과부하) 그 요청은 보조 모델로 보냅니다.",
    "每次请求先使用主模型。若失败（达到限额或过载），该请求改用备用模型。",
  ],
  "How much the model thinks before answering. Higher is slower and costs more output tokens.": [
    "모델이 답하기 전에 얼마나 생각하는지입니다. 높을수록 느리고 출력 토큰이 더 듭니다.",
    "模型在回答前思考的程度。越高越慢，消耗的输出 token 也越多。",
  ],
  "{name} API key is required. Enter it above to translate.": ["{name} API 키가 필요합니다. 위에 입력해야 번역할 수 있습니다.", "需要 {name} API 密钥。请在上方输入后再翻译。"],
  "Stored only in this browser, sent to your local backend.": ["이 브라우저에만 저장하고, 이 PC 의 백엔드로만 보냅니다.", "仅保存在此浏览器中，并只发送到本机后端。"],
  " Empty = server default key.": [" 비워 두면 서버 기본 키를 씁니다.", " 留空则使用服务器默认密钥。"],
  " Get one at ": [" 키 받는 곳: ", " 获取地址："],
  "How many API calls PROCESS ALL uses. 1 = send all text in one call, 2 = split it into two calls. auto = 1 call per {n} pages.": [
    "PROCESS ALL 이 보내는 API 요청 수입니다. 1 = 글 전부를 한 번에 보냄, 2 = 둘로 나눠 보냄. 자동 = {n}쪽마다 요청 1개.",
    "PROCESS ALL 使用的 API 调用次数。1 = 一次发送全部文本，2 = 分成两次发送。自动 = 每 {n} 页调用 1 次。",
  ],
};

//t("문장", { 이름: 값 }): 고른 언어의 문장을 돌려주고 {이름} 자리를 값으로 채운다
export const translator = (ui: UiLang) => (s: string, vars: Record<string, string | number> = {}) =>
  Object.entries(vars).reduce((out, [k, v]) => out.split(`{${k}}`).join(String(v)), ui === "en" ? s : TEXT[s]?.[ui === "ko" ? 0 : 1] ?? s);

//번역 언어 이름(값은 Gemini 에 넘기는 영어 이름)을 화면 언어로 보여 준다. 브라우저가 아는 이름을 쓴다
const CODES: Record<string, string> = {
  "Japanese": "ja", "Korean": "ko", "English": "en", "Chinese (Simplified)": "zh-Hans", "Chinese (Traditional)": "zh-Hant",
  "Spanish": "es", "French": "fr", "German": "de", "Italian": "it", "Portuguese": "pt", "Russian": "ru", "Ukrainian": "uk", "Polish": "pl", "Dutch": "nl",
  "Swedish": "sv", "Norwegian": "no", "Danish": "da", "Finnish": "fi", "Czech": "cs", "Hungarian": "hu", "Romanian": "ro", "Greek": "el", "Turkish": "tr",
  "Arabic": "ar", "Hebrew": "he", "Persian": "fa", "Hindi": "hi", "Bengali": "bn", "Urdu": "ur", "Tamil": "ta",
  "Vietnamese": "vi", "Thai": "th", "Indonesian": "id", "Malay": "ms", "Filipino": "fil", "Burmese": "my", "Khmer": "km", "Mongolian": "mn",
};
export const langName = (ui: UiLang, name: string) =>
  ui === "en" || !CODES[name] ? name : new Intl.DisplayNames([ui === "zh" ? "zh-Hans" : ui], { type: "language" }).of(CODES[name]) ?? name;
