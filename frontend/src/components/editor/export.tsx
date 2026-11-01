import JSZip from "jszip";
import { API } from "../../api";

//폴더 선택을 지원하지 않는 브라우저(Firefox/Safari)면 zip 으로 내려받는다

export type ExportFile = { name: string; blob: Blob };

export function pageFileName(index: number, original?: string) {
  const stem = (original ?? "")
    .replace(/\.[^.]+$/, "")
    .replace(/[<>:"/\\|?*]/g, "_")
    .trim();
  return `${String(index + 1).padStart(4, "0")}_${stem || "page"}.png`;
}

//lib.dom 에 아직 없는 타입만 최소로
type DirHandle = {
  getFileHandle(name: string, opts?: { create?: boolean }): Promise<{
    createWritable(): Promise<{ write(data: Blob): Promise<void>; close(): Promise<void> }>;
  }>;
};
declare global {
  interface Window {
    showDirectoryPicker?(opts?: { mode?: "read" | "readwrite" }): Promise<DirHandle>;
    pywebview?: { api: { pick_folder(): Promise<{ path: string } | null>; fullscreen(): Promise<void> } };
  }
}

//데스크톱 앱(pywebview): 윈도우 폴더 선택창을 앱이 띄우고, 파일은 백엔드 /export 가 그 폴더에 쓴다.
//브라우저 API 로 쓰면 "127.0.0.1 이 파일을 수정하도록 허용하시겠습니까?" 창이 뜨는데, 이 길은 그게 없다
export const isDesktopApp = () => !!window.pywebview?.api;

export async function pickFolderDesktop(): Promise<string | null> {
  const picked = await window.pywebview!.api.pick_folder();
  return picked?.path ?? null;
}

export async function saveToFolderDesktop(folder: string, file: ExportFile) {
  const form = new FormData();
  form.append("folder", folder);
  form.append("name", file.name);
  form.append("file", file.blob, file.name);
  const r = await fetch(`${API}/export`, { method: "POST", body: form });
  if (!r.ok) throw new Error(`${r.status} ${(await r.text()).slice(0, 200)}`);
}

export async function pickFolder() {
  if (!window.showDirectoryPicker) return undefined;
  try {
    return await window.showDirectoryPicker({ mode: "readwrite" });
  } catch {
    return null;
  }
}

export async function saveToFolder(dir: DirHandle, file: ExportFile) {
  const handle = await dir.getFileHandle(file.name, { create: true });
  const w = await handle.createWritable();
  await w.write(file.blob);
  await w.close();
}

export async function downloadZip(name: string, files: ExportFile[]) {
  const zip = new JSZip();
  for (const f of files) zip.file(f.name, f.blob);
  const blob = await zip.generateAsync({ type: "blob" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${name || "manga"}.zip`;
  a.click();
  URL.revokeObjectURL(url);
}
