/**
 * The "Add contact" and "Add company" modals' frame and inputs.
 *
 * `noValidate`: an invalid email reaches the API, whose errors show on their field like
 * all the others. A closed modal is unmounted, which is what clears it.
 */

import { useEffect, useId, type FormEvent, type ReactNode } from "react";
import type { FormErrors } from "./formErrors";

export function FormModal({
  title,
  errors,
  isSubmitting,
  onClose,
  onSubmit,
  children,
}: {
  title: string;
  errors: FormErrors;
  isSubmitting: boolean;
  onClose: () => void;
  onSubmit: () => void;
  children: ReactNode;
}) {
  const titleId = useId();

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="w-full max-w-lg rounded-xl bg-white shadow-xl"
      >
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
          <h2 id={titleId} className="text-lg font-semibold text-gray-900">
            {title}
          </h2>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <form noValidate onSubmit={handleSubmit} className="space-y-4 px-6 py-4">
          {errors.general.length > 0 && (
            <div role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
              {errors.general.map((message) => (
                <p key={message}>{message}</p>
              ))}
            </div>
          )}
          {children}
          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="rounded-lg bg-primary-500 px-4 py-2 text-sm font-medium text-white hover:bg-primary-600 disabled:opacity-50"
            >
              {title}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export function FormField({
  label,
  type = "text",
  value,
  errors = [],
  autoFocus = false,
  onChange,
}: {
  label: string;
  type?: "text" | "email" | "tel";
  value: string;
  errors?: string[];
  autoFocus?: boolean;
  onChange: (value: string) => void;
}) {
  const inputId = useId();
  const errorId = useId();
  const hasErrors = errors.length > 0;

  return (
    <div>
      <label htmlFor={inputId} className="mb-1 block text-sm font-medium text-gray-700">
        {label}
      </label>
      <input
        id={inputId}
        type={type}
        value={value}
        autoFocus={autoFocus}
        aria-invalid={hasErrors || undefined}
        aria-describedby={hasErrors ? errorId : undefined}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-hidden focus:ring-1 focus:ring-primary-500"
      />
      {hasErrors && (
        <p id={errorId} className="mt-1 text-xs text-red-600">
          {errors.join(" ")}
        </p>
      )}
    </div>
  );
}
