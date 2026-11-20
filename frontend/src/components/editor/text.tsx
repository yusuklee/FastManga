import { memo, useState } from "react";
import type { Content, FontChoice } from "../../Project";
import { FontPicker } from "./fontpicker";

const PAGE_FONT: FontChoice = { family: "Page font" }; //상자 폰트 안 정함 = 설정의 폰트

//오른쪽 글자 목록. 항목을 누르면 원문과 번역문 입력칸이 펼쳐진다
export const Text = memo(function Text({
  contents,
  fonts,
  selectedArea,
  onSelect,
  onEdit,
  onRemove,
  onRestore,
  onCollapse,
}: {
  contents: Content[];
  fonts: FontChoice[]; //상자별 폰트 선택지
  selectedArea: string | null;
  onSelect: (key: string | null) => void;
  onEdit: (id: number, patch: Partial<Content>) => void; //번역문·폰트·크기 직접 고치기 → 그림·내보내기에 반영
  onRemove?: (id: number) => void; //상자 지우기 (오탐)
  onRestore?: (id: number) => void; //원상복구: 그 자리를 원문으로 되돌리고 상자를 뺀다
  onCollapse?: () => void; //패널 접기 (VS Code 사이드바처럼)
}) {
  const [openGroup, setOpenGroup] = useState(true);

  return (
    <div>
      <div className="flex h-9 items-center border-b pr-2 text-[11px] font-semibold tracking-wide text-muted-foreground">
        <button onClick={() => setOpenGroup(!openGroup)} className="flex h-full flex-1 items-center gap-2 px-3 hover:bg-muted">
          <span className="text-[9px]">{openGroup ? "▼" : "▶"}</span>
          <span>TEXT</span>
          <span className="rounded-full bg-muted px-2 py-0.5 text-[10px]">{contents.length}</span>
        </button>
        {onCollapse && (
          <button className="rounded px-1 text-[10px] hover:bg-muted" onClick={onCollapse} title="Collapse">▶</button>
        )}
      </div>

      {openGroup && (
        <div className="grid gap-1.5 p-2">
          {contents.length === 0 && (
            <div className="flex flex-col items-center gap-1 px-2 py-10 text-center">
              <span className="text-2xl">💬</span>
              <p className="text-sm font-medium text-muted-foreground">No detections</p>
            </div>
          )}
          {contents.map((c) => {
            const key = `${c.id}`;
            const open = selectedArea === key;
            return (
              <div
                key={c.id}
                onClick={() => onSelect(open ? null : key)}
                className={`cursor-pointer rounded-lg border p-2.5 transition-colors ${
                  open ? "border-primary bg-accent/60" : "border-border bg-background hover:bg-muted"
                }`}
              >
                <p className="text-sm leading-snug">{c.translated ?? c.word}</p>
                {open && (
                  <div className="mt-2 border-t pt-2">
                    <p className="text-[10px] font-medium text-muted-foreground">Source</p>
                    <p className="text-xs text-muted-foreground">{c.word}</p>
                    {c.user && (
                      <div className="mt-2" onClick={(e) => e.stopPropagation()}>
                        <p className="text-[10px] font-medium text-muted-foreground">Style{c.group != null && " (whole linked group)"}</p>
                        <div className="mt-0.5 flex overflow-hidden rounded-lg border text-xs">
                          {([[true, "Auto", "Sound-effect lettering measured from the original"], [false, "Settings", "Font from Settings, original text size"]] as const).map(([sfx, label, tip]) => (
                            <button key={label} type="button" title={tip} className={`flex-1 px-2 py-1 ${!!c.sfx === sfx ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`} onClick={() => onEdit(c.id, { sfx })}>{label}</button>
                          ))}
                        </div>
                      </div>
                    )}
                    <p className="mt-2 text-[10px] font-medium text-muted-foreground">Translation</p>
                    <textarea
                      value={c.translated ?? ""}
                      rows={2}
                      placeholder="Type the translation"
                      onClick={(e) => e.stopPropagation()}
                      onChange={(e) => onEdit(c.id, { translated: e.target.value })}
                      className="mt-0.5 w-full resize-y rounded-md border bg-background px-2 py-1 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                    />
                    <div className="mt-2 flex items-end gap-2" onClick={(e) => e.stopPropagation()}>
                      <label>
                        <p className="text-[10px] font-medium text-muted-foreground">Text color</p>
                        <input type="color" value={c.color_set ?? (c.color && c.color.length === 7 ? c.color : "#000000")} onChange={(e) => onEdit(c.id, { color_set: e.target.value })} className="h-8 w-12 cursor-pointer rounded-lg border bg-background p-0.5" title="Text color" />
                      </label>
                      <label>
                        <p className="text-[10px] font-medium text-muted-foreground">Outline</p>
                        <input type="color" value={c.stroke_set ?? (c.stroke && c.stroke.length === 7 ? c.stroke : "#ffffff")} onChange={(e) => onEdit(c.id, { stroke_set: e.target.value })} className={`h-8 w-12 cursor-pointer rounded-lg border bg-background p-0.5 ${c.stroke_set === null ? "opacity-30" : ""}`} title="Outline color" />
                      </label>
                      <button type="button" className={`h-8 rounded-lg border px-2 text-xs hover:bg-muted ${c.stroke_set === null ? "bg-primary text-primary-foreground" : ""}`} onClick={() => onEdit(c.id, { stroke_set: null })} title="No outline">No outline</button>
                      <button type="button" className="h-8 rounded-lg border px-2 text-xs hover:bg-muted" onClick={() => onEdit(c.id, { color_set: undefined, stroke_set: undefined })} title="Use the colors measured from the original">Auto</button>
                    </div>
                    <div className="mt-2 flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                      <div className="min-w-0 flex-1">
                        <p className="text-[10px] font-medium text-muted-foreground">Font</p>
                        <FontPicker inline fonts={[PAGE_FONT, ...fonts]} value={fonts.find((f) => f.family === c.font) ?? PAGE_FONT} onChange={(f) => onEdit(c.id, { font: f === PAGE_FONT ? undefined : f.family })} />
                      </div>
                      <label className="w-20">
                        <p className="text-[10px] font-medium text-muted-foreground">Size px</p>
                        <input
                          type="number" min={4} max={999} placeholder="auto" value={c.size ?? ""}
                          onChange={(e) => onEdit(c.id, { size: e.target.value ? Math.max(4, Number(e.target.value)) : undefined })}
                          className="h-8 w-full rounded-lg border bg-background px-2 text-sm outline-none focus:border-primary"
                        />
                      </label>
                      {onRestore && (
                        <button type="button" className="mt-4 h-8 rounded-lg border px-2 text-xs hover:bg-muted" onClick={() => onRestore(c.id)} title="Put the original text back here">Restore</button>
                      )}
                      {onRemove && (
                        <button type="button" className="mt-4 h-8 rounded-lg border px-2 text-xs text-destructive hover:bg-muted" onClick={() => onRemove(c.id)} title="Remove this box">Delete</button>
                      )}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
});
