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
  onCollapse,
}: {
  contents: Content[];
  fonts: FontChoice[]; //상자별 폰트 선택지
  selectedArea: string | null;
  onSelect: (key: string | null) => void;
  onEdit: (id: number, patch: Partial<Content>) => void; //번역문·폰트·크기 직접 고치기 → 그림·내보내기에 반영
  onRemove?: (id: number) => void; //상자 지우기 (오탐)
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
                    <p className="mt-2 text-[10px] font-medium text-muted-foreground">Translation</p>
                    <textarea
                      value={c.translated ?? ""}
                      rows={2}
                      placeholder="Type the translation"
                      onClick={(e) => e.stopPropagation()}
                      onChange={(e) => onEdit(c.id, { translated: e.target.value })}
                      className="mt-0.5 w-full resize-y rounded-md border bg-background px-2 py-1 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                    />
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
