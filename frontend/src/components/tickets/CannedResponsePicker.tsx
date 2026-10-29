/**
 * Canned-response picker shown above the reply composer.
 *
 * Displays a filterable list of templates available to the current agent
 * (personal + shared). Selection emits the template; the caller is
 * responsible for variable substitution and insertion into the textarea.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useCannedResponses } from "@/hooks/useCannedResponses";
import type { CannedResponse } from "@/api/cannedResponses";

interface Props {
  open: boolean;
  initialQuery?: string;
  onSelect: (response: CannedResponse) => void;
  onClose: () => void;
}

export function CannedResponsePicker({
  open,
  initialQuery = "",
  onSelect,
  onClose,
}: Props) {
  if (!open) return null;
  // Remount the panel whenever the seed query changes so its local state
  // (search text, highlighted row) starts fresh — same as reopening it.
  return (
    <PickerPanel
      key={initialQuery}
      initialQuery={initialQuery}
      onSelect={onSelect}
      onClose={onClose}
    />
  );
}

function PickerPanel({
  initialQuery,
  onSelect,
  onClose,
}: Omit<Props, "open" | "initialQuery"> & { initialQuery: string }) {
  const { data: responses } = useCannedResponses();
  const [query, setQuery] = useState(initialQuery);
  const [activeIdx, setActiveIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const frame = requestAnimationFrame(() => inputRef.current?.focus());
    return () => cancelAnimationFrame(frame);
  }, []);

  const filtered = useMemo(() => {
    const list = responses ?? [];
    const q = query.trim().toLowerCase();
    if (!q) return list.slice(0, 50);
    return list
      .filter((r) => {
        return (
          r.name.toLowerCase().includes(q) ||
          r.shortcut.toLowerCase().includes(q) ||
          r.body.toLowerCase().includes(q)
        );
      })
      .slice(0, 50);
  }, [responses, query]);

  useEffect(() => {
    const handle = (e: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        onClose();
      }
    };
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [onClose]);

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const item = filtered[activeIdx];
      if (item) onSelect(item);
    } else if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    }
  };

  return (
    <div
      ref={containerRef}
      className="absolute bottom-full left-0 z-20 mb-2 w-96 max-w-full rounded-xl border border-gray-200 bg-white shadow-lg"
    >
      <div className="border-b border-gray-100 p-2">
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setActiveIdx(0);
          }}
          onKeyDown={handleKey}
          placeholder="Search templates…"
          className="w-full rounded-md border border-gray-200 px-3 py-1.5 text-sm focus:border-primary-500 focus:outline-hidden"
        />
      </div>
      <div className="max-h-72 overflow-y-auto">
        {filtered.length === 0 ? (
          <div className="px-4 py-6 text-center text-sm text-gray-500">
            {responses?.length === 0
              ? "No templates yet. Create one in Settings → Canned Responses."
              : "No template matches."}
          </div>
        ) : (
          filtered.map((cr, idx) => (
            <button
              key={cr.id}
              type="button"
              onMouseEnter={() => setActiveIdx(idx)}
              onClick={() => onSelect(cr)}
              className={
                "block w-full border-b border-gray-50 px-3 py-2 text-left last:border-b-0 " +
                (idx === activeIdx ? "bg-primary-50" : "hover:bg-gray-50")
              }
            >
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-gray-900">
                  {cr.name}
                </span>
                {cr.shortcut && (
                  <span className="rounded-sm bg-gray-100 px-1.5 py-0.5 font-mono text-xs text-gray-600">
                    /{cr.shortcut}
                  </span>
                )}
                {cr.is_shared && (
                  <span className="rounded-full bg-emerald-50 px-1.5 py-0.5 text-[10px] text-emerald-700">
                    Shared
                  </span>
                )}
              </div>
              <p className="mt-0.5 line-clamp-2 whitespace-pre-wrap text-xs text-gray-500">
                {cr.body}
              </p>
            </button>
          ))
        )}
      </div>
      <div className="flex items-center justify-between border-t border-gray-100 px-3 py-1.5 text-[11px] text-gray-400">
        <span>↑↓ to navigate · ↵ to insert · esc to close</span>
        <span>{filtered.length} result{filtered.length === 1 ? "" : "s"}</span>
      </div>
    </div>
  );
}
