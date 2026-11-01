/**
 * A value that turns into an input on demand. It saves on Enter or on blur and Escape
 * cancels. A refused value stays in the input, with the reason next to it.
 */

import { useId, useRef, useState, type ReactNode } from "react";

const PENCIL_PATH =
  "M15.232 5.232l3.536 3.536M4 20h4l10.5-10.5a2.5 2.5 0 10-3.536-3.536L4 16.5V20z";

export function InlineField({
  label,
  value,
  type = "text",
  readOnly = false,
  onSave,
  children,
}: {
  label: string;
  value: string;
  type?: "text" | "email" | "tel" | "url";
  readOnly?: boolean;
  /** Resolves to why it was refused, nothing if it wasn't. */
  onSave: (value: string) => Promise<string[]>;
  /** How the value shows when not editing, if not as plain text. */
  children?: ReactNode;
}) {
  const inputId = useId();
  const errorId = useId();
  const [draft, setDraft] = useState<string | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [isSaving, setIsSaving] = useState(false);
  // False once the input is going away: removing a focused input can fire its blur.
  const isOpen = useRef(false);

  const open = () => {
    isOpen.current = true;
    setDraft(value);
  };

  const close = () => {
    isOpen.current = false;
    setDraft(null);
    setErrors([]);
  };

  const commit = async () => {
    if (draft === null || isSaving || !isOpen.current) return;
    const next = draft.trim();
    if (next === value) {
      close();
      return;
    }
    setIsSaving(true);
    const refused = await onSave(next);
    setIsSaving(false);
    if (refused.length > 0) setErrors(refused);
    else close();
  };

  if (draft !== null && !readOnly) {
    const hasErrors = errors.length > 0;
    return (
      <div>
        <label htmlFor={inputId} className="mb-1 block text-xs font-medium text-gray-500">
          {label}
        </label>
        <input
          id={inputId}
          type={type}
          value={draft}
          autoFocus
          readOnly={isSaving}
          aria-busy={isSaving || undefined}
          aria-invalid={hasErrors || undefined}
          aria-describedby={hasErrors ? errorId : undefined}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => void commit()}
          onKeyDown={(e) => {
            if (e.key === "Enter") void commit();
            if (e.key === "Escape") close();
          }}
          className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:border-primary-500 focus:outline-hidden focus:ring-1 focus:ring-primary-500"
        />
        {hasErrors && (
          <p id={errorId} className="mt-1 text-xs text-red-600">
            {errors.join(" ")}
          </p>
        )}
      </div>
    );
  }

  return (
    <div>
      <div className="text-xs font-medium text-gray-500">{label}</div>
      <div className="flex min-w-0 items-center gap-2 text-sm text-gray-900">
        <div className="min-w-0 break-words">
          {children ?? (value || <span className="text-gray-400">Not set</span>)}
        </div>
        {!readOnly && (
          <button
            type="button"
            aria-label={`Edit ${label.toLowerCase()}`}
            onClick={open}
            className="shrink-0 rounded-sm p-0.5 text-gray-400 hover:text-gray-600"
          >
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={PENCIL_PATH} />
            </svg>
          </button>
        )}
      </div>
    </div>
  );
}
