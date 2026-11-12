import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";

export type DetectWhat = { text: boolean; sfx: boolean };

//PROCESS·PROCESS ALL 을 누르면 뜨는 창: 처리할 페이지와 번역할 항목을 체크로 고른다
export function ProcessDialog({
  open,
  pages,
  initialPages,
  what,
  onCancel,
  onStart,
}: {
  open: boolean;
  pages: string[];
  initialPages: string[];
  what: DetectWhat;
  onCancel: () => void;
  onStart: (pages: string[], what: DetectWhat) => void;
}) {
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [items, setItems] = useState<DetectWhat>(what);
  useEffect(() => {
    if (!open) return;
    setChecked(new Set(initialPages));
    setItems({ ...what, sfx: false });   //의성어는 열 때마다 꺼진 채로
  }, [open]);
  if (!open) return null;

  const toggle = (p: string) =>
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(p)) next.delete(p); else next.add(p);
      return next;
    });
  const selected = pages.filter((p) => checked.has(p));
  const canStart = selected.length > 0 && (items.text || items.sfx);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onCancel}>
      <div className="w-[640px] max-w-[92vw] rounded-lg border border-neutral-700 bg-neutral-900 p-5 text-neutral-100 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-sm font-semibold">Process</h2>

        <div className="mt-4 flex items-center justify-between">
          <p className="text-xs font-medium text-neutral-400">Pages ({selected.length}/{pages.length})</p>
          <div className="flex gap-1">
            <button type="button" className="rounded border border-neutral-600 px-2 py-0.5 text-[11px] hover:bg-neutral-800" onClick={() => setChecked(new Set(pages))}>All</button>
            <button type="button" className="rounded border border-neutral-600 px-2 py-0.5 text-[11px] hover:bg-neutral-800" onClick={() => setChecked(new Set())}>None</button>
          </div>
        </div>
        <div className="mt-2 grid max-h-80 grid-cols-5 gap-2 overflow-y-auto rounded-lg border border-neutral-700 p-2">
          {pages.map((p, i) => (
            <label key={p} className={`relative cursor-pointer overflow-hidden rounded border-2 ${checked.has(p) ? "border-primary" : "border-transparent opacity-50 hover:opacity-80"}`}>
              <img src={p} alt="" loading="lazy" className="block aspect-[3/4] w-full object-cover" />
              <span className="absolute left-0 top-0 flex items-center gap-1 rounded-br bg-black/70 px-1.5 py-0.5 text-[11px]">
                <input type="checkbox" className="accent-primary" checked={checked.has(p)} onChange={() => toggle(p)} />
                {i + 1}
              </span>
            </label>
          ))}
        </div>

        <p className="mt-4 text-xs font-medium text-neutral-400">Translate</p>
        <div className="mt-1 flex gap-4">
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="accent-primary" checked={items.text} onChange={(e) => setItems({ ...items, text: e.target.checked })} />
            Text
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="accent-primary" checked={items.sfx} onChange={(e) => setItems({ ...items, sfx: e.target.checked })} />
            Sound effects
          </label>
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <Button variant="outline" size="sm" className="border-neutral-600 bg-transparent text-neutral-100 hover:bg-neutral-800 hover:text-neutral-100" onClick={onCancel}>Cancel</Button>
          <Button size="sm" disabled={!canStart} onClick={() => onStart(selected, items)}>Start</Button>
        </div>
      </div>
    </div>
  );
}
