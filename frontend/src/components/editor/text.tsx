import { memo, useEffect, useRef, useState } from "react";
import type { Content, FontChoice } from "../../Project";
import { FontPicker } from "./fontpicker";

const PAGE_FONT: FontChoice = { family: "Page font" }; //상자 폰트 안 정함 = 설정의 폰트

//오른쪽 글자 목록. 항목을 누르면 원문과 번역문 입력칸이 펼쳐진다
export const Text = memo(function Text({
  contents,
  fonts,
  selected,
  onSelect,
  onSelectAll,
  onEditMany,
  onEdit,
  onRemove,
  onRestore,
  onCollapse,
}: {
  contents: Content[];
  fonts: FontChoice[]; //상자별 폰트 선택지
  selected: number[]; //고른 상자들. 하나면 그 항목이 펼쳐지고, 여럿이면 표시만 된다
  onSelect: (id: number, add: boolean) => void; //add = Ctrl+클릭 (고른 것에 넣거나 빼기)
  onSelectAll: (ids: number[]) => void; //한 번에 고르기 (All / Text / Sound Effect 버튼)
  onEditMany: (ids: number[], patch: Partial<Content>) => void; //고른 여러 상자의 서식을 한 번에 바꾸기
  onEdit: (id: number, patch: Partial<Content>) => void; //번역문·폰트·크기 직접 고치기 → 그림·내보내기에 반영
  onRemove?: (id: number) => void; //상자 지우기 (오탐)
  onRestore?: (id: number) => void; //원상복구: 그 자리를 원문으로 되돌리고 상자를 뺀다
  onCollapse?: () => void; //패널 접기 (VS Code 사이드바처럼)
}) {
  const [openGroup, setOpenGroup] = useState(true);
  //화면에서 글자를 눌러 골랐을 때 그 항목이 목록에 보이게 한다
  const listRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (selected.length === 1) listRef.current?.querySelector(`[data-box="${selected[0]}"]`)?.scrollIntoView({ block: "nearest" });
  }, [selected]);
  //한 번에 고르기: 이미 딱 그것들이 골라져 있으면 다시 눌러 푼다
  const sets: [string, number[]][] = [["All", contents.map((c) => c.id)], ["Text", contents.filter((c) => !c.sfx).map((c) => c.id)], ["Sound Effect", contents.filter((c) => c.sfx).map((c) => c.id)]];
  //여러 개를 골랐을 때 한 번에 바꾸는 칸에 보여 줄 값: 고른 것 중 첫 상자의 것
  const first = selected.length > 1 ? contents.find((c) => selected.includes(c.id)) : undefined;
  const same = (ids: number[]) => ids.length > 0 && ids.length === selected.length && ids.every((id) => selected.includes(id));

  return (
    <div>
      {/* 제목 · 한 번에 고르기 · 여러 개 바꾸기는 목록을 스크롤해도 위에 붙어 있다 */}
      <div className="sticky top-0 z-10 bg-background">
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

      {openGroup && contents.length > 0 && (
        <div className="flex items-center gap-1 border-b px-2 py-1.5 text-[11px]">
          <span className="mr-1 text-muted-foreground">Select</span>
          {sets.map(([label, ids]) => (
            <button key={label} type="button" disabled={!ids.length} title={`Select ${label === "All" ? "every text" : label === "Sound Effect" ? "the sound effects" : "the dialogue"} on this page (Ctrl+click a text to add or remove one)`}
              className={`rounded-md border px-2 py-0.5 disabled:opacity-40 ${same(ids) ? "border-primary bg-primary text-primary-foreground" : "hover:bg-muted"}`}
              onClick={() => onSelectAll(same(ids) ? [] : ids)}>{label}</button>
          ))}
          {selected.length > 1 && <span className="ml-auto text-muted-foreground">{selected.length} selected</span>}
        </div>
      )}
      {/* 여러 개를 골랐을 때: 고른 것 전부의 글자색·테두리·폰트·크기를 한 번에 바꾼다 (항목 하나를 펼쳤을 때와 같은 칸) */}
      {openGroup && first && (
        <div data-batch className="border-b bg-accent/40 px-2 py-2">
          <div className="flex items-end gap-2">
            <label>
              <p className="text-[10px] font-medium text-muted-foreground">Text color</p>
              <input type="color" value={first.color_set ?? (first.color && first.color.length === 7 ? first.color : "#000000")} onChange={(e) => onEditMany(selected, { color_set: e.target.value })} className="h-8 w-12 cursor-pointer rounded-lg border bg-background p-0.5" title="Text color of every selected text" />
            </label>
            <label>
              <p className="text-[10px] font-medium text-muted-foreground">Outline</p>
              <input type="color" value={first.stroke_set ?? (first.stroke && first.stroke.length === 7 ? first.stroke : "#ffffff")} onChange={(e) => onEditMany(selected, { stroke_set: e.target.value })} className={`h-8 w-12 cursor-pointer rounded-lg border bg-background p-0.5 ${first.stroke_set === null ? "opacity-30" : ""}`} title="Outline color of every selected text" />
            </label>
            <button type="button" aria-pressed={first.stroke_set === null} className={`h-8 rounded-lg border px-2 text-xs ${first.stroke_set === null ? "border-primary bg-primary text-primary-foreground" : "bg-background hover:bg-muted"}`} onClick={() => onEditMany(selected, { stroke_set: first.stroke_set === null ? undefined : null })} title="Turn the outline off / back on">No outline</button>
            <button type="button" className="h-8 rounded-lg border bg-background px-2 text-xs hover:bg-muted" onClick={() => onEditMany(selected, { color_set: undefined, stroke_set: undefined })} title="Use the colors measured from the original">Auto</button>
          </div>
          <div className="mt-2 flex items-end gap-2">
            <div className="min-w-0 flex-1">
              <p className="text-[10px] font-medium text-muted-foreground">Font</p>
              <FontPicker inline fonts={[PAGE_FONT, ...fonts]} value={fonts.find((f) => f.family === first.font) ?? PAGE_FONT} onChange={(f) => onEditMany(selected, { font: f === PAGE_FONT ? undefined : f.family })} />
            </div>
            <label className="w-20">
              <p className="text-[10px] font-medium text-muted-foreground">Size px</p>
              <input type="number" min={4} max={999} placeholder="auto" value={first.size ?? ""} onChange={(e) => onEditMany(selected, { size: e.target.value ? Math.max(4, Number(e.target.value)) : undefined })} className="h-8 w-full rounded-lg border bg-background px-2 text-sm outline-none focus:border-primary" />
            </label>
          </div>
        </div>
      )}
      </div>
      {openGroup && (
        <div ref={listRef} className="grid gap-1.5 p-2">
          {contents.length === 0 && (
            <div className="flex flex-col items-center gap-1 px-2 py-10 text-center">
              <span className="text-2xl">💬</span>
              <p className="text-sm font-medium text-muted-foreground">No detections</p>
            </div>
          )}
          {contents.map((c) => {
            const picked = selected.includes(c.id), open = picked && selected.length === 1;
            return (
              <div
                key={c.id}
                data-box={c.id}
                onClick={(e) => onSelect(c.id, e.ctrlKey || e.metaKey)}
                className={`cursor-pointer rounded-lg border p-2.5 transition-colors ${
                  picked ? "border-primary bg-accent/60" : "border-border bg-background hover:bg-muted"
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
                      <button type="button" aria-pressed={c.stroke_set === null} className={`h-8 rounded-lg border px-2 text-xs ${c.stroke_set === null ? "border-primary bg-primary text-primary-foreground" : "hover:bg-muted"}`} onClick={() => onEdit(c.id, { stroke_set: c.stroke_set === null ? undefined : null })} title="Turn the outline off / back on">No outline</button>
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
                      {c.move && (
                        <button type="button" className="mt-4 h-8 rounded-lg border px-2 text-xs hover:bg-muted" onClick={() => onEdit(c.id, { move: undefined })} title="Put the text back where it was drawn">Unmove</button>
                      )}
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
