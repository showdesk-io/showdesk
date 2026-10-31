/**
 * The custom attributes of a contact or a company, for either: one typed input per live
 * definition. Values without one, as an archived definition's, can only be read.
 */

import { useId, useState } from "react";
import { useAttributeDefs } from "@/hooks/useAttributeDefs";
import type { AttributeDef, AttributeDefEntity } from "@/types";
import { ListError, ListLoading } from "./ListParts";
import { safeHttpUrl } from "./safeUrl";

const INPUT_CLASS =
  "w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:border-primary-500 focus:outline-hidden focus:ring-1 focus:ring-primary-500";
const LABEL_CLASS = "mb-1 block text-xs font-medium text-gray-500";

const INPUT_TYPES: Partial<Record<AttributeDef["type"], string>> = {
  number: "number",
  date: "date",
  url: "url",
};

function isSet(value: unknown): boolean {
  return value !== null && value !== undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function toText(value: unknown): string {
  if (!isSet(value)) return "";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

/** What the API takes for what's in the input: emptied, a field sends null. */
function toPayload(type: AttributeDef["type"], text: string): unknown {
  if (!text) return null;
  if (type === "number") return Number(text);
  if (type === "boolean") return text === "true";
  return text;
}

export function AttributeEditor({
  entity,
  values: rawValues,
  readOnly = false,
  onSave,
}: {
  entity: AttributeDefEntity;
  values: unknown;
  readOnly?: boolean;
  /** Resolves to why it was refused, nothing if it wasn't. */
  onSave: (key: string, value: unknown) => Promise<string[]>;
}) {
  const { data: defs, isLoading, isFetching, refetch } = useAttributeDefs(entity);

  if (isLoading) return <ListLoading label="Loading attributes" />;
  if (!defs) {
    return (
      <ListError
        message="Could not load attributes."
        onRetry={() => void refetch()}
        isRetrying={isFetching}
      />
    );
  }

  // The column is free-form JSON: nothing but the API's writes keeps it an object.
  const values = isRecord(rawValues) ? rawValues : {};
  const live = defs
    .filter((def) => !def.is_archived)
    .sort((a, b) => a.position - b.position);
  const liveKeys = new Set(live.map((def) => def.key));
  const orphans = Object.entries(values).filter(
    ([key, value]) => !liveKeys.has(key) && isSet(value),
  );
  const editable = readOnly ? [] : live;
  const readable = readOnly ? live.filter((def) => isSet(values[def.key])) : [];

  if (editable.length === 0 && readable.length === 0 && orphans.length === 0) {
    return <p className="text-sm text-gray-400">No attributes.</p>;
  }

  return (
    <div className="space-y-3">
      {editable.map((def) => (
        <AttributeField
          key={def.id}
          def={def}
          value={values[def.key]}
          onSave={(value) => onSave(def.key, value)}
        />
      ))}
      {readable.map((def) => (
        <ReadOnlyValue key={def.id} label={def.label} value={values[def.key]} type={def.type} />
      ))}
      {orphans.map(([key, value]) => (
        <ReadOnlyValue
          key={key}
          label={key}
          value={value}
          type={defs.find((def) => def.key === key)?.type}
        />
      ))}
    </div>
  );
}

function ReadOnlyValue({
  label,
  value,
  type,
}: {
  label: string;
  value: unknown;
  type: AttributeDef["type"] | undefined;
}) {
  const text = toText(value);
  const href = type === "url" ? safeHttpUrl(value) : null;

  return (
    <div>
      <div className="text-xs font-medium text-gray-500">{label}</div>
      <div className="break-words text-sm text-gray-900">
        {href ? (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary-700 hover:underline"
          >
            {text}
          </a>
        ) : (
          text
        )}
      </div>
    </div>
  );
}

function AttributeField({
  def,
  value,
  onSave,
}: {
  def: AttributeDef;
  value: unknown;
  onSave: (value: unknown) => Promise<string[]>;
}) {
  const inputId = useId();
  const errorId = useId();
  const descriptionId = useId();
  // Null: what's stored shows. Otherwise, what's being typed, saved or was refused.
  const [draft, setDraft] = useState<string | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [isSaving, setIsSaving] = useState(false);

  const stored = toText(value);
  const shown = draft ?? stored;
  const hasErrors = errors.length > 0;

  const describedBy =
    [def.description && descriptionId, hasErrors && errorId].filter(Boolean).join(" ") ||
    undefined;
  const shared = {
    id: inputId,
    "aria-busy": isSaving || undefined,
    "aria-invalid": hasErrors || undefined,
    "aria-describedby": describedBy,
  };

  const submit = async (input: string) => {
    if (isSaving) return;
    const text = input.trim();
    if (text === stored) {
      setDraft(null);
      setErrors([]);
      return;
    }
    setDraft(text);
    setIsSaving(true);
    const refused = await onSave(toPayload(def.type, text));
    setIsSaving(false);
    setErrors(refused);
    if (refused.length === 0) setDraft(null);
  };

  const help = (
    <>
      {def.description && (
        <p id={descriptionId} className="mt-1 text-xs text-gray-400">
          {def.description}
        </p>
      )}
      {hasErrors && (
        <p id={errorId} className="mt-1 text-xs text-red-600">
          {errors.join(" ")}
        </p>
      )}
    </>
  );

  if (def.type === "boolean") {
    return (
      <div>
        <div className="flex items-center gap-2">
          <input
            {...shared}
            type="checkbox"
            // Neither yes nor no: unset is a state of its own.
            ref={(element) => {
              if (element) element.indeterminate = shown === "";
            }}
            checked={shown === "true"}
            onChange={(e) => void submit(String(e.target.checked))}
            className="rounded-sm border-gray-300"
          />
          <label htmlFor={inputId} className="text-sm text-gray-700">
            {def.label}
          </label>
          {shown !== "" && (
            <button
              type="button"
              aria-label={`Clear ${def.label}`}
              onClick={() => void submit("")}
              className="text-xs text-gray-400 hover:text-gray-600 hover:underline"
            >
              Clear
            </button>
          )}
        </div>
        {help}
      </div>
    );
  }

  if (def.type === "enum") {
    const options =
      stored && !def.options.includes(stored) ? [...def.options, stored] : def.options;
    return (
      <div>
        <label htmlFor={inputId} className={LABEL_CLASS}>
          {def.label}
        </label>
        <select
          {...shared}
          value={shown}
          onChange={(e) => void submit(e.target.value)}
          className={INPUT_CLASS}
        >
          <option value="">Not set</option>
          {options.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
        {help}
      </div>
    );
  }

  const href = def.type === "url" ? safeHttpUrl(stored) : null;
  return (
    <div>
      <label htmlFor={inputId} className={LABEL_CLASS}>
        {def.label}
      </label>
      <input
        {...shared}
        type={INPUT_TYPES[def.type] ?? "text"}
        step={def.type === "number" ? "any" : undefined}
        value={shown}
        readOnly={isSaving}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={(e) => {
          // Not a number yet: the browser reads it as empty, which would clear the value.
          if (e.currentTarget.validity.badInput) {
            setErrors([`Not a valid ${def.type} value.`]);
            return;
          }
          void submit(shown);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
        }}
        className={INPUT_CLASS}
      />
      {href && (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`Open ${def.label}`}
          className="mt-1 inline-block text-xs text-primary-700 hover:underline"
        >
          Open
        </a>
      )}
      {help}
    </div>
  );
}
