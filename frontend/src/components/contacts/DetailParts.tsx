/**
 * What the contact and company detail pages share.
 */

import type { ReactNode } from "react";
import { Link } from "react-router";

export function BackLink({ to, label }: { to: string; label: string }) {
  return (
    <Link to={to} className="text-sm text-primary-700 hover:underline">
      <span aria-hidden="true">&larr; </span>
      {label}
    </Link>
  );
}

export function DetailNotFound({
  message,
  backTo,
  backLabel,
}: {
  message: string;
  backTo: string;
  backLabel: string;
}) {
  return (
    <div className="p-6 text-center text-gray-500">
      <p>{message}</p>
      <div className="mt-2">
        <BackLink to={backTo} label={backLabel} />
      </div>
    </div>
  );
}

export function SectionHeading({ children }: { children: ReactNode }) {
  return <h2 className="mb-2 text-sm font-semibold text-gray-900">{children}</h2>;
}

/** A label and a value that can't be edited. */
export function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="text-xs font-medium text-gray-500">{label}</div>
      <div className="break-words text-sm text-gray-900">{children}</div>
    </div>
  );
}

export const CARD_CLASS = "rounded-xl border border-gray-200 bg-white p-4";
export const ACTION_BUTTON_CLASS =
  "w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50";
export const DANGER_BUTTON_CLASS =
  "w-full rounded-lg border border-red-300 px-3 py-1.5 text-sm text-red-700 hover:bg-red-50 disabled:opacity-50";
