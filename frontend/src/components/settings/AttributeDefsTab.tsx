/**
 * Settings tab for an entity's custom attributes: definitions are archived, never deleted.
 * Admins manage them, agents read them.
 */

import { useId, useState, type FormEvent } from "react";
import { clsx } from "clsx";
import toast from "react-hot-toast";
import type { AttributeDefCreate, AttributeDefUpdate } from "@/api/attributeDefs";
import { FormField } from "@/components/contacts/FormModal";
import {
  fieldErrors,
  NO_ERRORS,
  readFormErrors,
  type FormErrors,
} from "@/components/contacts/formErrors";
import { TH_CLASS } from "@/components/contacts/ListParts";
import {
  useAttributeDefs,
  useCreateAttributeDef,
  useUpdateAttributeDef,
} from "@/hooks/useAttributeDefs";
import type { AttributeDef, AttributeDefEntity, AttributeDefType } from "@/types";
import {
  formatOptions,
  MAX_ACTIVE_ATTRIBUTES,
  parseOptions,
  suggestAttributeKey,
  TYPE_LABELS,
  validateAttributeKey,
} from "./attributeDefForm";

const TITLES: Record<AttributeDefEntity, string> = {
  contact: "Contact attributes",
  company: "Company attributes",
};

const FORM_FIELDS = ["key", "label", "type", "description", "options"];
const LIMIT_REACHED = `At most ${MAX_ACTIVE_ATTRIBUTES} attributes can be active. Archive one first.`;
const CONTROL_CLASS =
  "w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-hidden focus:ring-1 focus:ring-primary-500";

/** What the form is open on, null when it's closed. */
type FormTarget = { mode: "create" } | { mode: "edit"; definition: AttributeDef } | null;

export function AttributeDefsTab({
  entity,
  isAdmin,
}: {
  entity: AttributeDefEntity;
  isAdmin: boolean;
}) {
  const { data: definitions, isLoading, isError } = useAttributeDefs(entity);
  const [formTarget, setFormTarget] = useState<FormTarget>(null);

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary-500 border-t-transparent" />
      </div>
    );
  }
  if (isError || !definitions) {
    return (
      <div role="alert" className="mx-auto max-w-5xl text-center text-sm text-red-600">
        Could not load these attributes.
      </div>
    );
  }

  const activeCount = definitions.filter((definition) => !definition.is_archived).length;
  const atLimit = activeCount >= MAX_ACTIVE_ATTRIBUTES;
  // The API sorts on position, then label: a position keeps them in creation order.
  const nextPosition = Math.max(-1, ...definitions.map((item) => item.position)) + 1;

  return (
    <div className="mx-auto max-w-5xl">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-baseline gap-3">
          <h2 className="text-lg font-semibold text-gray-900">{TITLES[entity]}</h2>
          <span className="text-sm text-gray-500">
            {activeCount} / {MAX_ACTIVE_ATTRIBUTES}
          </span>
        </div>
        {isAdmin && (
          <button
            type="button"
            onClick={() => setFormTarget({ mode: "create" })}
            disabled={atLimit}
            className="rounded-lg bg-primary-500 px-4 py-2 text-sm font-medium text-white hover:bg-primary-600 disabled:opacity-50"
          >
            + New attribute
          </button>
        )}
      </div>

      {isAdmin && atLimit && <p className="mb-4 text-sm text-gray-500">{LIMIT_REACHED}</p>}

      {isAdmin && formTarget && (
        <AttributeDefForm
          key={formTarget.mode === "edit" ? formTarget.definition.id : "create"}
          entity={entity}
          definition={formTarget.mode === "edit" ? formTarget.definition : null}
          nextPosition={nextPosition}
          disabled={formTarget.mode === "create" && atLimit}
          onClose={() => setFormTarget(null)}
        />
      )}

      {definitions.length === 0 ? (
        <div className="rounded-xl border border-gray-200 bg-white px-6 py-12 text-center text-gray-500">
          No attributes yet.
        </div>
      ) : (
        <AttributeDefTable
          entity={entity}
          definitions={definitions}
          isAdmin={isAdmin}
          atLimit={atLimit}
          onEdit={(definition) => setFormTarget({ mode: "edit", definition })}
        />
      )}
    </div>
  );
}

function AttributeDefTable({
  entity,
  definitions,
  isAdmin,
  atLimit,
  onEdit,
}: {
  entity: AttributeDefEntity;
  definitions: AttributeDef[];
  isAdmin: boolean;
  atLimit: boolean;
  onEdit: (definition: AttributeDef) => void;
}) {
  const update = useUpdateAttributeDef(entity);

  const setArchived = (definition: AttributeDef, isArchived: boolean) => {
    update.mutate(
      { id: definition.id, is_archived: isArchived },
      {
        onError: (error) => toast.error(fieldErrors(error, "is_archived").join(" ")),
      },
    );
  };

  return (
    <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white">
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            <th scope="col" className={TH_CLASS}>Label</th>
            <th scope="col" className={TH_CLASS}>Key</th>
            <th scope="col" className={TH_CLASS}>Type</th>
            <th scope="col" className={TH_CLASS}>Options</th>
            <th scope="col" className={TH_CLASS}>State</th>
            {isAdmin && (
              <th scope="col" className={TH_CLASS}>
                <span className="sr-only">Actions</span>
              </th>
            )}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {definitions.map((definition) => (
            <tr key={definition.id} className={clsx(definition.is_archived && "bg-gray-50")}>
              <td className="px-6 py-3 text-sm">
                <div
                  className={clsx(
                    "font-medium",
                    definition.is_archived ? "text-gray-500" : "text-gray-900",
                  )}
                >
                  {definition.label}
                </div>
                {definition.description && (
                  <div className="text-xs text-gray-500">{definition.description}</div>
                )}
              </td>
              <td className="px-6 py-3 font-mono text-xs text-gray-600">{definition.key}</td>
              <td className="px-6 py-3 text-sm text-gray-600">{TYPE_LABELS[definition.type]}</td>
              <td className="px-6 py-3 text-sm text-gray-600">
                {formatOptions(definition.options)}
              </td>
              <td className="px-6 py-3 text-sm text-gray-600">
                {definition.is_archived ? "Archived" : "Active"}
              </td>
              {isAdmin && (
                <td className="whitespace-nowrap px-6 py-3 text-right">
                  <button
                    type="button"
                    onClick={() => onEdit(definition)}
                    className="rounded-sm px-2 py-1 text-xs text-gray-500 hover:bg-gray-100 hover:text-gray-700"
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    onClick={() => setArchived(definition, !definition.is_archived)}
                    disabled={update.isPending || (definition.is_archived && atLimit)}
                    title={definition.is_archived && atLimit ? LIMIT_REACHED : undefined}
                    className="rounded-sm px-2 py-1 text-xs text-gray-500 hover:bg-gray-100 hover:text-gray-700 disabled:opacity-50"
                  >
                    {definition.is_archived ? "Unarchive" : "Archive"}
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Creates a definition, or edits `definition`, whose key and type can't change. */
function AttributeDefForm({
  entity,
  definition,
  nextPosition,
  disabled,
  onClose,
}: {
  entity: AttributeDefEntity;
  definition: AttributeDef | null;
  nextPosition: number;
  disabled: boolean;
  onClose: () => void;
}) {
  const create = useCreateAttributeDef(entity);
  const update = useUpdateAttributeDef(entity);
  const initialOptions = formatOptions(definition?.options ?? []);

  const [label, setLabel] = useState(definition?.label ?? "");
  const [key, setKey] = useState("");
  const [keyEdited, setKeyEdited] = useState(false);
  const [type, setType] = useState<AttributeDefType>(definition?.type ?? "string");
  const [description, setDescription] = useState(definition?.description ?? "");
  const [optionsText, setOptionsText] = useState(initialOptions);
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS);

  const typeId = useId();
  const descriptionId = useId();
  const isPending = create.isPending || update.isPending;

  const changeLabel = (value: string) => {
    setLabel(value);
    if (!definition && !keyEdited) setKey(suggestAttributeKey(value));
  };

  const changeKey = (value: string) => {
    setKey(value);
    // Emptied, it goes back to following the label.
    setKeyEdited(value !== "");
  };

  const validate = (): FormErrors["fields"] => {
    const fields: FormErrors["fields"] = {};
    if (!label.trim()) fields.label = ["A label is required."];
    if (!definition) {
      const keyError = validateAttributeKey(key);
      if (keyError) fields.key = [keyError];
    }
    if (type === "enum" && parseOptions(optionsText).length === 0) {
      fields.options = ["A list needs at least one option."];
    }
    return fields;
  };

  const refused = (error: unknown) => {
    const formErrors = readFormErrors(error, FORM_FIELDS);
    if (formErrors) setErrors(formErrors);
    else toast.error("Could not save this attribute.");
  };

  const submitCreate = () => {
    const data: AttributeDefCreate = {
      key,
      label: label.trim(),
      type,
      description: description.trim(),
      position: nextPosition,
      ...(type === "enum" ? { options: parseOptions(optionsText) } : {}),
    };
    create.mutate(data, {
      onSuccess: () => {
        toast.success("Attribute created.");
        onClose();
      },
      onError: refused,
    });
  };

  const submitUpdate = (current: AttributeDef) => {
    // Only what changed. Untouched, options aren't parsed back: one may hold a comma.
    const changes: AttributeDefUpdate = {};
    if (label.trim() !== current.label) changes.label = label.trim();
    if (description.trim() !== current.description) changes.description = description.trim();
    if (optionsText !== initialOptions) {
      const options = parseOptions(optionsText);
      if (formatOptions(options) !== initialOptions) changes.options = options;
    }
    if (Object.keys(changes).length === 0) {
      onClose();
      return;
    }
    update.mutate(
      { id: current.id, ...changes },
      {
        onSuccess: () => {
          toast.success("Attribute updated.");
          onClose();
        },
        onError: refused,
      },
    );
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (isPending || disabled) return;
    const fields = validate();
    setErrors({ fields, general: [] });
    if (Object.keys(fields).length > 0) return;
    if (definition) submitUpdate(definition);
    else submitCreate();
  };

  return (
    <form
      noValidate
      onSubmit={handleSubmit}
      aria-label={definition ? "Edit attribute" : "New attribute"}
      className="mb-6 rounded-xl border border-gray-200 bg-white p-4"
    >
      <fieldset disabled={disabled} className="space-y-4">
        {errors.general.length > 0 && (
          <div role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
            {errors.general.map((message) => (
              <p key={message}>{message}</p>
            ))}
          </div>
        )}

        <div className="grid gap-4 sm:grid-cols-3">
          <FormField
            label="Label"
            value={label}
            errors={errors.fields.label}
            autoFocus
            onChange={changeLabel}
          />

          {definition ? (
            <div>
              <div className="mb-1 text-sm font-medium text-gray-700">Key</div>
              <code className="break-all py-2 font-mono text-sm text-gray-600">
                {definition.key}
              </code>
            </div>
          ) : (
            <FormField
              label="Key"
              value={key}
              errors={errors.fields.key}
              onChange={changeKey}
            />
          )}

          {definition ? (
            <div>
              <div className="mb-1 text-sm font-medium text-gray-700">Type</div>
              <div className="py-2 text-sm text-gray-600">{TYPE_LABELS[definition.type]}</div>
            </div>
          ) : (
            <div>
              <label htmlFor={typeId} className="mb-1 block text-sm font-medium text-gray-700">
                Type
              </label>
              <select
                id={typeId}
                value={type}
                onChange={(e) => setType(e.target.value as AttributeDefType)}
                className={CONTROL_CLASS}
              >
                {Object.entries(TYPE_LABELS).map(([value, typeLabel]) => (
                  <option key={value} value={value}>
                    {typeLabel}
                  </option>
                ))}
              </select>
              {errors.fields.type && (
                <p className="mt-1 text-xs text-red-600">{errors.fields.type.join(" ")}</p>
              )}
            </div>
          )}
        </div>

        {!definition && (
          <p className="text-xs text-gray-500">The key and the type can't change afterwards.</p>
        )}

        <div>
          <label
            htmlFor={descriptionId}
            className="mb-1 block text-sm font-medium text-gray-700"
          >
            Description
          </label>
          <textarea
            id={descriptionId}
            rows={2}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className={CONTROL_CLASS}
          />
          {errors.fields.description && (
            <p className="mt-1 text-xs text-red-600">{errors.fields.description.join(" ")}</p>
          )}
        </div>

        {type === "enum" && (
          <div>
            <FormField
              label="Options"
              value={optionsText}
              errors={errors.fields.options}
              onChange={setOptionsText}
            />
            <p className="mt-1 text-xs text-gray-500">
              Comma-separated.
              {definition && " Removing an option doesn't change stored values."}
            </p>
          </div>
        )}

      </fieldset>

      <div className="mt-4 flex justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={isPending || disabled}
          className="rounded-lg bg-primary-500 px-4 py-1.5 text-sm font-medium text-white hover:bg-primary-600 disabled:opacity-50"
        >
          {definition ? "Save" : "Create"}
        </button>
      </div>
    </form>
  );
}
