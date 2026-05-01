/**
 * Manage the active org's verified/pending domains.
 *
 * Admins can:
 *   - Add a domain (admin_email auto-verify or DNS TXT challenge).
 *   - Verify a pending DNS row ("Check now").
 *   - Regenerate a stale DNS token.
 *   - Toggle the branding/email-routing flags.
 *   - Delete a row.
 *
 * Non-admins see the list read-only.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import toast from "react-hot-toast";
import { clsx } from "clsx";
import { formatDistanceToNow } from "date-fns";
import {
  createOrganizationDomain,
  deleteOrganizationDomain,
  fetchOrganizationDomains,
  regenerateOrganizationDomainToken,
  updateOrganizationDomain,
  verifyOrganizationDomain,
} from "@/api/organizationDomains";
import type {
  DomainStatus,
  DomainVerificationMethod,
  OrganizationDomain,
} from "@/types";

interface DomainsListProps {
  isAdmin: boolean;
}

export function DomainsList({ isAdmin }: DomainsListProps) {
  const queryClient = useQueryClient();
  const { data: domains = [], isLoading } = useQuery({
    queryKey: ["organization-domains"],
    queryFn: fetchOrganizationDomains,
  });
  const [showAddModal, setShowAddModal] = useState(false);

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["organization-domains"] });

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-6">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Domains</h2>
          <p className="mt-1 text-sm text-gray-500">
            Verified domains let you brand the workspace and auto-route
            teammate signups.
          </p>
        </div>
        {isAdmin && (
          <button
            type="button"
            onClick={() => setShowAddModal(true)}
            className="shrink-0 rounded-lg bg-primary-500 px-3 py-2 text-sm font-medium text-white hover:bg-primary-600"
          >
            Add domain
          </button>
        )}
      </div>

      {isLoading ? (
        <div className="flex justify-center py-8">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary-500 border-t-transparent" />
        </div>
      ) : domains.length === 0 ? (
        <p className="rounded-lg bg-gray-50 px-4 py-6 text-center text-sm text-gray-500">
          No domains yet. Add one to enable branding or domain-based join
          requests.
        </p>
      ) : (
        <ul className="divide-y divide-gray-100">
          {domains.map((d) => (
            <DomainRow
              key={d.id}
              domain={d}
              isAdmin={isAdmin}
              onChange={invalidate}
            />
          ))}
        </ul>
      )}

      {showAddModal && (
        <AddDomainModal
          onClose={() => setShowAddModal(false)}
          onCreated={() => {
            void invalidate();
            setShowAddModal(false);
          }}
        />
      )}
    </div>
  );
}

// ─── Row ────────────────────────────────────────────────────────────────

function DomainRow({
  domain,
  isAdmin,
  onChange,
}: {
  domain: OrganizationDomain;
  isAdmin: boolean;
  onChange: () => void;
}) {
  const [showDns, setShowDns] = useState(false);

  const deleteMutation = useMutation({
    mutationFn: () => deleteOrganizationDomain(domain.id),
    onSuccess: () => {
      toast.success(`${domain.domain} removed`);
      onChange();
    },
    onError: () => toast.error("Could not remove domain."),
  });

  const togglePurpose = useMutation({
    mutationFn: (patch: { is_branding?: boolean; is_email_routing?: boolean }) =>
      updateOrganizationDomain(domain.id, patch),
    onSuccess: onChange,
    onError: (err: unknown) => {
      const detail =
        isAxiosError(err) && err.response?.data
          ? (err.response.data as { is_branding?: string[] }).is_branding?.[0]
          : null;
      toast.error(detail || "Could not update purposes.");
    },
  });

  const isPendingDns =
    domain.status === "pending" && domain.verification_method === "dns_txt";
  // Legacy branding rows backfilled from the old scalar `domain` field
  // sit at status=pending with no method or token yet. Surface a way to
  // promote them into a real DNS challenge.
  const needsDnsKickoff =
    domain.status === "pending" &&
    domain.verification_method !== "dns_txt" &&
    !domain.verification_token;

  const startDns = useMutation({
    mutationFn: () => regenerateOrganizationDomainToken(domain.id),
    onSuccess: () => {
      onChange();
      setShowDns(true);
    },
    onError: () => toast.error("Could not start DNS verification."),
  });

  return (
    <li className="flex flex-col gap-2 py-4">
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-mono text-sm font-medium text-gray-900">
          {domain.domain}
        </span>
        <DomainStatusBadge status={domain.status} />
        {domain.verification_method === "dns_txt" && (
          <PurposeChip label="DNS verified" subtle />
        )}
        {domain.verification_method === "admin_email" && (
          <PurposeChip label="Admin email" subtle />
        )}
        {isAdmin ? (
          <div className="ml-auto flex items-center gap-2">
            {isPendingDns && (
              <button
                type="button"
                onClick={() => setShowDns((v) => !v)}
                className="text-xs text-primary-600 hover:text-primary-700"
              >
                {showDns ? "Hide instructions" : "Show DNS instructions"}
              </button>
            )}
            {needsDnsKickoff && (
              <button
                type="button"
                onClick={() => startDns.mutate()}
                disabled={startDns.isPending}
                className="text-xs text-primary-600 hover:text-primary-700 disabled:opacity-50"
              >
                {startDns.isPending ? "Starting..." : "Verify via DNS"}
              </button>
            )}
            <button
              type="button"
              onClick={() => deleteMutation.mutate()}
              disabled={deleteMutation.isPending}
              className="text-xs text-red-600 hover:text-red-700 disabled:opacity-50"
            >
              Delete
            </button>
          </div>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-3 text-xs text-gray-500">
        <PurposeToggle
          label="Branding"
          checked={domain.is_branding}
          disabled={!isAdmin || togglePurpose.isPending}
          onChange={(v) => togglePurpose.mutate({ is_branding: v })}
        />
        <PurposeToggle
          label="Email routing"
          checked={domain.is_email_routing}
          disabled={!isAdmin || togglePurpose.isPending}
          onChange={(v) => togglePurpose.mutate({ is_email_routing: v })}
        />
        {domain.verified_at && (
          <span>
            Verified {formatDistanceToNow(new Date(domain.verified_at))} ago
          </span>
        )}
        {!domain.verified_at && domain.last_check_at && (
          <span>
            Last checked {formatDistanceToNow(new Date(domain.last_check_at))} ago
          </span>
        )}
      </div>

      {(showDns || (isPendingDns && domain.last_check_at === null)) &&
        isPendingDns && (
          <DnsInstructionsPanel domain={domain} onChange={onChange} />
        )}

      {domain.status === "failed" && (
        <p className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">
          Verification failed. Another organization may have claimed this
          domain via DNS, or the TXT record was removed. Regenerate the
          token to try again.
        </p>
      )}
    </li>
  );
}

function PurposeToggle({
  label,
  checked,
  disabled,
  onChange,
}: {
  label: string;
  checked: boolean;
  disabled: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label
      className={clsx(
        "inline-flex items-center gap-1.5",
        disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer",
      )}
    >
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="h-3.5 w-3.5 rounded border-gray-300 text-primary-500 focus:ring-primary-500"
      />
      <span>{label}</span>
    </label>
  );
}

function PurposeChip({ label, subtle }: { label: string; subtle?: boolean }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
        subtle
          ? "bg-gray-100 text-gray-600"
          : "bg-primary-50 text-primary-700",
      )}
    >
      {label}
    </span>
  );
}

// ─── Status badge ───────────────────────────────────────────────────────

function DomainStatusBadge({ status }: { status: DomainStatus }) {
  const styles: Record<DomainStatus, { cls: string; label: string }> = {
    verified: {
      cls: "bg-green-50 text-green-700 ring-green-200",
      label: "Verified",
    },
    pending: {
      cls: "bg-amber-50 text-amber-700 ring-amber-200",
      label: "Pending",
    },
    failed: {
      cls: "bg-red-50 text-red-700 ring-red-200",
      label: "Failed",
    },
  };
  const { cls, label } = styles[status];
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        cls,
      )}
    >
      {label}
    </span>
  );
}

// ─── DNS instructions ───────────────────────────────────────────────────

function DnsInstructionsPanel({
  domain,
  onChange,
}: {
  domain: OrganizationDomain;
  onChange: () => void;
}) {
  const verifyMutation = useMutation({
    mutationFn: () => verifyOrganizationDomain(domain.id),
    onSuccess: ({ verified }) => {
      if (verified) {
        toast.success(`${domain.domain} is verified`);
      } else {
        toast(
          "TXT record not found yet. DNS can take a few minutes to propagate.",
          { icon: "⏳" },
        );
      }
      onChange();
    },
    onError: () => toast.error("Verification check failed."),
  });

  const regenerateMutation = useMutation({
    mutationFn: () => regenerateOrganizationDomainToken(domain.id),
    onSuccess: () => {
      toast.success("New token generated.");
      onChange();
    },
    onError: () => toast.error("Could not regenerate token."),
  });

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm">
      <p className="mb-3 font-medium text-amber-900">
        Add this DNS TXT record to verify ownership of {domain.domain}:
      </p>
      <CopyRow label="Name (Host)" value={domain.txt_record_name} />
      <CopyRow label="Value" value={domain.txt_record_value} />
      <p className="mt-3 text-xs text-amber-800">
        Once published, click "Check now". We also re-poll automatically
        every 15 minutes for up to 7 days.
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => verifyMutation.mutate()}
          disabled={verifyMutation.isPending}
          className="rounded-md bg-primary-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-600 disabled:opacity-50"
        >
          {verifyMutation.isPending ? "Checking..." : "Check now"}
        </button>
        <button
          type="button"
          onClick={() => regenerateMutation.mutate()}
          disabled={regenerateMutation.isPending}
          className="text-xs text-primary-600 hover:text-primary-700 disabled:opacity-50"
        >
          Regenerate token
        </button>
      </div>
    </div>
  );
}

function CopyRow({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    void navigator.clipboard.writeText(value).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };
  return (
    <div className="mb-2 flex items-center gap-2">
      <span className="w-28 shrink-0 text-xs font-medium text-amber-900">
        {label}
      </span>
      <code className="flex-1 overflow-x-auto rounded border border-amber-200 bg-white px-2 py-1 font-mono text-xs text-gray-800">
        {value}
      </code>
      <button
        type="button"
        onClick={copy}
        className="shrink-0 rounded border border-amber-300 bg-white px-2 py-1 text-xs hover:bg-amber-100"
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

// ─── Add modal ──────────────────────────────────────────────────────────

function AddDomainModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const [domain, setDomain] = useState("");
  const [isBranding, setIsBranding] = useState(true);
  const [isRouting, setIsRouting] = useState(true);
  const [method, setMethod] = useState<DomainVerificationMethod>("dns_txt");

  const createMutation = useMutation({
    mutationFn: () =>
      createOrganizationDomain({
        domain: domain.trim().toLowerCase(),
        is_branding: isBranding,
        is_email_routing: isRouting,
        verification_method: method,
      }),
    onSuccess: (created) => {
      if (created.status === "verified") {
        toast.success(`${created.domain} verified`);
      } else {
        toast.success(`${created.domain} added — verify via DNS to activate`);
      }
      onCreated();
    },
    onError: (err: unknown) => {
      if (isAxiosError(err) && err.response) {
        const data = err.response.data as {
          detail?: string;
          code?: string;
          domain?: string[];
        };
        if (data.code === "use_dns_instead") {
          toast.error(
            "This domain is verified by another organization. Switch to DNS verification to claim it.",
          );
          setMethod("dns_txt");
        } else if (data.code === "cannot_autoverify") {
          toast.error(
            data.detail ||
              "No admin in this org has a verified email on this domain. Use DNS verification instead.",
          );
          setMethod("dns_txt");
        } else if (data.domain && data.domain[0]) {
          toast.error(data.domain[0]);
        } else {
          toast.error(data.detail || "Could not add this domain.");
        }
      } else {
        toast.error("Could not add this domain.");
      }
    },
  });

  const canSubmit =
    domain.trim().length > 0 && (isBranding || isRouting) && !createMutation.isPending;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="mb-1 text-lg font-semibold text-gray-900">
          Add a domain
        </h3>
        <p className="mb-4 text-sm text-gray-500">
          You can pick admin-email auto-verify if you have an email on this
          domain, or verify ownership via DNS.
        </p>

        <div className="space-y-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              Domain
            </label>
            <input
              type="text"
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              placeholder="acme.com"
              autoFocus
            />
          </div>

          <div>
            <span className="mb-1 block text-sm font-medium text-gray-700">
              Purpose
            </span>
            <div className="flex flex-col gap-2">
              <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-gray-700">
                <input
                  type="checkbox"
                  checked={isBranding}
                  onChange={(e) => setIsBranding(e.target.checked)}
                  className="h-4 w-4 rounded border-gray-300 text-primary-500 focus:ring-primary-500"
                />
                Branding (display this domain publicly)
              </label>
              <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-gray-700">
                <input
                  type="checkbox"
                  checked={isRouting}
                  onChange={(e) => setIsRouting(e.target.checked)}
                  className="h-4 w-4 rounded border-gray-300 text-primary-500 focus:ring-primary-500"
                />
                Email routing (auto-route signups from @{domain || "this domain"})
              </label>
            </div>
          </div>

          <div>
            <span className="mb-1 block text-sm font-medium text-gray-700">
              Verification method
            </span>
            <div className="flex flex-col gap-2">
              <MethodOption
                checked={method === "dns_txt"}
                onChange={() => setMethod("dns_txt")}
                title="DNS TXT record"
                desc="Add a record to your DNS. Works for any domain you control."
              />
              <MethodOption
                checked={method === "admin_email"}
                onChange={() => setMethod("admin_email")}
                title="Admin email (auto)"
                desc="Available if you, or another admin, have a verified email on this domain."
              />
            </div>
          </div>
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => createMutation.mutate()}
            disabled={!canSubmit}
            className="rounded-lg bg-primary-500 px-4 py-2 text-sm font-medium text-white hover:bg-primary-600 disabled:opacity-50"
          >
            {createMutation.isPending ? "Adding..." : "Add domain"}
          </button>
        </div>
      </div>
    </div>
  );
}

function MethodOption({
  checked,
  onChange,
  title,
  desc,
}: {
  checked: boolean;
  onChange: () => void;
  title: string;
  desc: string;
}) {
  return (
    <label
      className={clsx(
        "flex cursor-pointer gap-3 rounded-lg border px-3 py-2 text-sm transition-colors",
        checked
          ? "border-primary-500 bg-primary-50"
          : "border-gray-200 hover:bg-gray-50",
      )}
    >
      <input
        type="radio"
        checked={checked}
        onChange={onChange}
        className="mt-0.5 h-4 w-4 border-gray-300 text-primary-500 focus:ring-primary-500"
      />
      <div className="flex-1">
        <div className="font-medium text-gray-900">{title}</div>
        <div className="text-xs text-gray-500">{desc}</div>
      </div>
    </label>
  );
}

// Re-export the badge so other components can reuse it later.
export { DomainStatusBadge };
