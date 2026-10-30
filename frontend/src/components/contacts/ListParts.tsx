/**
 * What the Contacts and Companies lists share: header with tabs, avatar, states
 * and pagination.
 */

import { useState, type ReactNode } from "react";
import { NavLink } from "react-router";
import { clsx } from "clsx";
import { safeHttpUrl } from "./safeUrl";

export const FILTER_SELECT_CLASS =
  "rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:border-primary-500 focus:outline-hidden";
export const TH_CLASS =
  "px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500";

const TABS = [
  { to: "/contacts", label: "Contacts" },
  { to: "/companies", label: "Companies" },
];

const PAGE_SIZES = [25, 50, 100];

export function ListHeader({
  title,
  countLabel,
  addLabel,
  onAdd,
  children,
}: {
  title: string;
  countLabel: string | null;
  addLabel: string;
  onAdd: () => void;
  children: ReactNode;
}) {
  return (
    <div className="border-b border-gray-200 bg-white px-6 pt-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-gray-900">{title}</h1>
        <div className="flex items-center gap-3">
          {countLabel && <span className="text-sm text-gray-500">{countLabel}</span>}
          <button
            onClick={onAdd}
            className="rounded-lg bg-primary-500 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-600"
          >
            <span aria-hidden="true">+ </span>
            {addLabel}
          </button>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">{children}</div>
      <nav aria-label="Contacts and companies" className="mt-3 flex gap-1">
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            className={({ isActive }) =>
              clsx(
                "rounded-t-lg px-4 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "border-b-2 border-primary-500 text-primary-700"
                  : "text-gray-500 hover:text-gray-700",
              )
            }
          >
            {tab.label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

export function SearchInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <input
      type="search"
      aria-label={label}
      placeholder={`${label}...`}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-64 rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:border-primary-500 focus:outline-hidden focus:ring-1 focus:ring-primary-500"
    />
  );
}

/**
 * An image next to a name, so with no alternative text. Initials if it's absent, broken or
 * not http(s). Someone else chose this URL: it isn't told who's looking.
 */
export function Avatar({
  url: rawUrl,
  name,
  square = false,
}: {
  url: string;
  name: string;
  square?: boolean;
}) {
  const [brokenUrl, setBrokenUrl] = useState<string | null>(null);
  const shape = square ? "rounded-lg" : "rounded-full";
  const url = safeHttpUrl(rawUrl);

  if (url && url !== brokenUrl) {
    return (
      <img
        src={url}
        alt=""
        referrerPolicy="no-referrer"
        onError={() => setBrokenUrl(url)}
        className={`h-8 w-8 shrink-0 object-cover ${shape}`}
      />
    );
  }
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word.charAt(0).toUpperCase())
    .join("");
  return (
    <div
      className={`flex h-8 w-8 shrink-0 items-center justify-center bg-primary-100 text-xs font-semibold text-primary-700 ${shape}`}
    >
      {initials || "?"}
    </div>
  );
}

export function ListLoading({ label }: { label: string }) {
  return (
    <div role="status" aria-label={label} className="flex items-center justify-center py-12">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary-500 border-t-transparent" />
    </div>
  );
}

export function ListError({
  message,
  onRetry,
  isRetrying,
}: {
  message: string;
  onRetry: () => void;
  isRetrying: boolean;
}) {
  return (
    <div className="py-12 text-center">
      <p role="alert" className="text-gray-500">
        {message}
      </p>
      <button
        onClick={onRetry}
        disabled={isRetrying}
        className="mt-3 rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-50"
      >
        Try again
      </button>
    </div>
  );
}

export function ListEmpty({ message }: { message: string }) {
  return <div className="py-12 text-center text-gray-500">{message}</div>;
}

export function Pagination({
  count,
  page,
  pageSize,
  onPageChange,
  onPageSizeChange,
}: {
  count: number;
  page: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  onPageSizeChange: (pageSize: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(count / pageSize));
  const buttonClass =
    "rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-50";

  return (
    <div className="flex items-center justify-between border-t border-gray-200 bg-white px-6 py-3">
      <select
        aria-label="Rows per page"
        value={pageSize}
        onChange={(e) => onPageSizeChange(Number(e.target.value))}
        className={FILTER_SELECT_CLASS}
      >
        {PAGE_SIZES.map((size) => (
          <option key={size} value={size}>
            {size}
          </option>
        ))}
      </select>
      <div className="flex items-center gap-3">
        <span className="text-sm text-gray-500">
          Page {page} of {pages}
        </span>
        <button
          aria-label="Previous page"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
          className={buttonClass}
        >
          Previous
        </button>
        <button
          aria-label="Next page"
          disabled={page >= pages}
          onClick={() => onPageChange(page + 1)}
          className={buttonClass}
        >
          Next
        </button>
      </div>
    </div>
  );
}
