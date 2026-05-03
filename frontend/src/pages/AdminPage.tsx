/**
 * Platform Admin page — organization management and usage stats.
 */

import { useState } from "react";
import { clsx } from "clsx";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import {
  fetchPlatformOrganizations,
  createPlatformOrganization,
  suspendPlatformOrganization,
  deletePlatformOrganization,
  fetchOrganizationStats,
  fetchPlatformOrganizationDetail,
  updatePlatformOrganization,
  fetchPlatformUsage,
  type UsagePeriod,
} from "@/api/admin";
import type { Plan } from "@/types";

const adminTabs = ["Organizations", "Usage"] as const;
type AdminTab = (typeof adminTabs)[number];

export function AdminPage() {
  const [activeTab, setActiveTab] = useState<AdminTab>("Organizations");
  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-gray-200 bg-white px-6 pt-6">
        <h1 className="mb-4 text-2xl font-bold text-gray-900">
          Platform Admin
        </h1>
        <div className="flex gap-1">
          {adminTabs.map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={clsx(
                "rounded-t-lg px-4 py-2 text-sm font-medium transition-colors",
                activeTab === tab
                  ? "border-b-2 border-primary-500 text-primary-700"
                  : "text-gray-500 hover:text-gray-700",
              )}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>
      <div className="flex-1 overflow-auto p-6">
        {activeTab === "Organizations" && <OrganizationsPanel />}
        {activeTab === "Usage" && <UsagePanel />}
      </div>
    </div>
  );
}

// ── Organizations Panel ──────────────────────────────────────────────

function OrganizationsPanel() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [showCreate, setShowCreate] = useState(false);
  const [selectedOrgId, setSelectedOrgId] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["platform-organizations", search, page],
    queryFn: () => fetchPlatformOrganizations({ search, page, page_size: 20 }),
  });

  const suspendMutation = useMutation({
    mutationFn: suspendPlatformOrganization,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["platform-organizations"] });
      toast.success("Organization status updated");
    },
    onError: () => toast.error("Failed to update organization status"),
  });

  const deleteMutation = useMutation({
    mutationFn: deletePlatformOrganization,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["platform-organizations"] });
      setSelectedOrgId(null);
      toast.success("Organization deleted");
    },
    onError: () => toast.error("Failed to delete organization"),
  });

  const orgs = data?.results ?? [];
  const totalCount = data?.count ?? 0;
  const totalPages = Math.ceil(totalCount / 20);

  return (
    <div className="space-y-4">
      {/* Header bar */}
      <div className="flex items-center justify-between gap-4">
        <div className="relative flex-1 max-w-md">
          <input
            type="text"
            placeholder="Search organizations..."
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            className="w-full rounded-lg border border-gray-300 py-2 pl-9 pr-3 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
          />
          <svg
            className="absolute left-3 top-2.5 h-4 w-4 text-gray-400"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
            />
          </svg>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="rounded-lg bg-primary-500 px-4 py-2 text-sm font-medium text-white hover:bg-primary-600"
        >
          New Organization
        </button>
      </div>

      {/* Table */}
      <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                Organization
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                Slug
              </th>
              <th className="px-6 py-3 text-center text-xs font-medium uppercase tracking-wider text-gray-500">
                Agents
              </th>
              <th className="px-6 py-3 text-center text-xs font-medium uppercase tracking-wider text-gray-500">
                Tickets
              </th>
              <th className="px-6 py-3 text-center text-xs font-medium uppercase tracking-wider text-gray-500">
                Status
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                Created
              </th>
              <th className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {isLoading ? (
              <tr>
                <td colSpan={7} className="px-6 py-8 text-center text-sm text-gray-400">
                  Loading...
                </td>
              </tr>
            ) : orgs.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-6 py-8 text-center text-sm text-gray-400">
                  No organizations found.
                </td>
              </tr>
            ) : (
              orgs.map((org) => (
                <tr
                  key={org.id}
                  className="cursor-pointer hover:bg-gray-50"
                  onClick={() => setSelectedOrgId(org.id)}
                >
                  <td className="whitespace-nowrap px-6 py-4">
                    <div className="text-sm font-medium text-gray-900">
                      {org.name}
                    </div>
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-500">
                    {org.slug}
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-center text-sm text-gray-700">
                    {org.agent_count}
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-center text-sm text-gray-700">
                    {org.ticket_count}
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-center">
                    <span
                      className={clsx(
                        "inline-flex rounded-full px-2 py-0.5 text-xs font-medium",
                        org.is_active
                          ? "bg-green-100 text-green-800"
                          : "bg-red-100 text-red-800",
                      )}
                    >
                      {org.is_active ? "Active" : "Suspended"}
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-500">
                    {new Date(org.created_at).toLocaleDateString()}
                  </td>
                  <td
                    className="whitespace-nowrap px-6 py-4 text-right text-sm"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <button
                      onClick={() => suspendMutation.mutate(org.id)}
                      className={clsx(
                        "mr-2 rounded px-2 py-1 text-xs font-medium",
                        org.is_active
                          ? "bg-yellow-100 text-yellow-800 hover:bg-yellow-200"
                          : "bg-green-100 text-green-800 hover:bg-green-200",
                      )}
                    >
                      {org.is_active ? "Suspend" : "Activate"}
                    </button>
                    <button
                      onClick={() => {
                        if (
                          window.confirm(
                            `Delete "${org.name}"? This cannot be undone.`,
                          )
                        ) {
                          deleteMutation.mutate(org.id);
                        }
                      }}
                      className="rounded bg-red-100 px-2 py-1 text-xs font-medium text-red-800 hover:bg-red-200"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between border-t border-gray-200 bg-white px-6 py-3">
            <p className="text-sm text-gray-500">
              {totalCount} organization{totalCount !== 1 && "s"}
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
                className="rounded border border-gray-300 px-3 py-1 text-sm disabled:opacity-50"
              >
                Previous
              </button>
              <span className="flex items-center px-2 text-sm text-gray-600">
                {page} / {totalPages}
              </span>
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className="rounded border border-gray-300 px-3 py-1 text-sm disabled:opacity-50"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Create modal */}
      {showCreate && (
        <CreateOrganizationModal onClose={() => setShowCreate(false)} />
      )}

      {/* Detail side panel */}
      {selectedOrgId && (
        <OrganizationDetailPanel
          orgId={selectedOrgId}
          onClose={() => setSelectedOrgId(null)}
        />
      )}
    </div>
  );
}

// ── Create Organization Modal ────────────────────────────────────────

function CreateOrganizationModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");

  const createMutation = useMutation({
    mutationFn: createPlatformOrganization,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["platform-organizations"] });
      toast.success("Organization created");
      onClose();
    },
    onError: () => toast.error("Failed to create organization"),
  });

  const handleNameChange = (value: string) => {
    setName(value);
    if (!slug || slug === toSlug(name)) {
      setSlug(toSlug(value));
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    createMutation.mutate({ name, slug });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
        <h2 className="mb-4 text-lg font-semibold text-gray-900">
          New Organization
        </h2>
        <p className="mb-4 text-xs text-gray-500">
          Add domains for branding or email routing from the org's Settings
          page after creation.
        </p>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700">
              Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => handleNameChange(e.target.value)}
              required
              className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">
              Slug
            </label>
            <input
              type="text"
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              required
              pattern="[a-z0-9-]+"
              className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
            />
          </div>
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
              disabled={createMutation.isPending}
              className="rounded-lg bg-primary-500 px-4 py-2 text-sm font-medium text-white hover:bg-primary-600 disabled:opacity-50"
            >
              {createMutation.isPending ? "Creating..." : "Create"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Organization Detail Panel ────────────────────────────────────────

function OrganizationDetailPanel({
  orgId,
  onClose,
}: {
  orgId: string;
  onClose: () => void;
}) {
  const { data: orgsData } = useQuery({
    queryKey: ["platform-organizations"],
    queryFn: () => fetchPlatformOrganizations({ page_size: 100 }),
  });

  const { data: detail } = useQuery({
    queryKey: ["platform-organization-detail", orgId],
    queryFn: () => fetchPlatformOrganizationDetail(orgId),
  });

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ["platform-org-stats", orgId],
    queryFn: () => fetchOrganizationStats(orgId),
  });

  const org = orgsData?.results.find((o) => o.id === orgId);

  if (!org) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30">
      <div
        className="absolute inset-0"
        onClick={onClose}
      />
      <div className="relative w-full max-w-lg overflow-auto bg-white shadow-xl">
        <div className="sticky top-0 flex items-center justify-between border-b border-gray-200 bg-white px-6 py-4">
          <h2 className="text-lg font-semibold text-gray-900">{org.name}</h2>
          <button
            onClick={onClose}
            className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="space-y-6 p-6">
          {/* Info */}
          <div className="grid grid-cols-2 gap-4">
            <InfoItem label="Slug" value={org.slug} />
            <InfoItem
              label="Status"
              value={org.is_active ? "Active" : "Suspended"}
            />
            <InfoItem
              label="Created"
              value={new Date(org.created_at).toLocaleDateString()}
            />
          </div>

          {/* Plan + feature flags */}
          {detail && <PlanFeatureFlagsEditor detail={detail} />}

          {/* Stats */}
          {statsLoading ? (
            <div className="text-sm text-gray-400">Loading stats...</div>
          ) : stats ? (
            <>
              <StatsSection title="Tickets" stats={stats.tickets} />
              <StatsSection title="Agents" stats={stats.agents} />
              <div className="grid grid-cols-3 gap-4">
                <StatCard label="Videos" value={stats.videos.total} />
                <StatCard label="Teams" value={stats.teams} />
                <StatCard label="Tags" value={stats.tags} />
              </div>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}

// ── Plan + Feature Flags editor ──────────────────────────────────────

const PLAN_OPTIONS: { value: Plan; label: string }[] = [
  { value: "free", label: "Free" },
  { value: "starter", label: "Cloud Starter" },
  { value: "business", label: "Cloud Business" },
  { value: "enterprise", label: "Enterprise" },
];

// Mirrors PLAN_DEFAULT_FEATURES in apps/organizations/models.py. Kept
// in sync manually -- the backend response also returns
// `enabled_features` so the rendered tri-state matches reality.
const KNOWN_FLAGS = [
  "bulk_actions",
  "custom_branding",
  "sla_policies",
  "ai_categorization",
  "audit_log",
  "sso",
  "webhooks",
] as const;

const PLAN_DEFAULT_FEATURES_FE: Record<Plan, Set<string>> = {
  free: new Set(),
  starter: new Set(["bulk_actions", "custom_branding"]),
  business: new Set([
    "bulk_actions",
    "custom_branding",
    "sla_policies",
    "ai_categorization",
    "webhooks",
  ]),
  enterprise: new Set(KNOWN_FLAGS),
};

function PlanFeatureFlagsEditor({
  detail,
}: {
  detail: import("@/types").PlatformOrganizationDetail;
}) {
  const queryClient = useQueryClient();
  const [plan, setPlan] = useState<Plan>(detail.plan);
  const [overrides, setOverrides] = useState<Record<string, boolean>>(
    detail.feature_flag_overrides ?? {},
  );
  const [initialised, setInitialised] = useState(detail.id);

  // Re-seed local state when the panel switches to a different org.
  if (initialised !== detail.id) {
    setPlan(detail.plan);
    setOverrides(detail.feature_flag_overrides ?? {});
    setInitialised(detail.id);
  }

  const saveMutation = useMutation({
    mutationFn: (data: Partial<import("@/types").PlatformOrganizationDetail>) =>
      updatePlatformOrganization(detail.id, data),
    onSuccess: () => {
      toast.success("Plan & flags updated");
      void queryClient.invalidateQueries({
        queryKey: ["platform-organization-detail", detail.id],
      });
    },
    onError: () => toast.error("Failed to update plan / flags"),
  });

  const planDefaults = PLAN_DEFAULT_FEATURES_FE[plan];
  const dirty =
    plan !== detail.plan ||
    JSON.stringify(overrides) !==
      JSON.stringify(detail.feature_flag_overrides ?? {});

  // For each flag, the resolved state used to render the toggle:
  //   override wins, otherwise the plan default.
  const resolved = (flag: string): boolean => {
    if (flag in overrides) return overrides[flag] === true;
    return planDefaults.has(flag);
  };

  const setOverride = (flag: string, value: boolean | null) => {
    setOverrides((prev) => {
      const next = { ...prev };
      if (value === null) delete next[flag];
      else next[flag] = value;
      return next;
    });
  };

  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold text-gray-700">
        Plan & feature flags
      </h3>
      <div className="space-y-3 rounded-lg border border-gray-200 p-4">
        <div>
          <label className="mb-1 block text-xs font-medium uppercase text-gray-500">
            Plan
          </label>
          <select
            value={plan}
            onChange={(e) => setPlan(e.target.value as Plan)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none"
          >
            {PLAN_OPTIONS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </div>

        <div>
          <div className="mb-2 flex items-center justify-between">
            <label className="text-xs font-medium uppercase text-gray-500">
              Features
            </label>
            <span className="text-[10px] text-gray-400">
              Plan default · override
            </span>
          </div>
          <ul className="space-y-1.5">
            {KNOWN_FLAGS.map((flag) => {
              const overridden = flag in overrides;
              const isOn = resolved(flag);
              return (
                <li
                  key={flag}
                  className="flex items-center justify-between rounded-md px-2 py-1.5 text-xs hover:bg-gray-50"
                >
                  <div>
                    <div className="font-mono text-gray-800">{flag}</div>
                    <div className="text-[10px] text-gray-400">
                      Plan default:{" "}
                      {planDefaults.has(flag) ? "on" : "off"}
                      {overridden && (
                        <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-800">
                          Overridden
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="flex shrink-0 gap-1">
                    <button
                      type="button"
                      onClick={() => setOverride(flag, true)}
                      className={clsx(
                        "rounded px-2 py-0.5 text-[10px] font-medium",
                        isOn && (overridden || planDefaults.has(flag))
                          ? "bg-green-100 text-green-700"
                          : "text-gray-400 hover:bg-gray-100",
                      )}
                    >
                      ON
                    </button>
                    <button
                      type="button"
                      onClick={() => setOverride(flag, false)}
                      className={clsx(
                        "rounded px-2 py-0.5 text-[10px] font-medium",
                        !isOn
                          ? "bg-red-100 text-red-700"
                          : "text-gray-400 hover:bg-gray-100",
                      )}
                    >
                      OFF
                    </button>
                    <button
                      type="button"
                      onClick={() => setOverride(flag, null)}
                      disabled={!overridden}
                      title="Reset to plan default"
                      className="rounded px-2 py-0.5 text-[10px] text-gray-400 hover:bg-gray-100 disabled:opacity-30"
                    >
                      ↺
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>

        {dirty && (
          <div className="flex justify-end gap-2 border-t border-gray-100 pt-3">
            <button
              type="button"
              onClick={() => {
                setPlan(detail.plan);
                setOverrides(detail.feature_flag_overrides ?? {});
              }}
              className="rounded-lg px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-100"
            >
              Discard
            </button>
            <button
              type="button"
              onClick={() =>
                saveMutation.mutate({
                  plan,
                  feature_flag_overrides: overrides,
                })
              }
              disabled={saveMutation.isPending}
              className="rounded-lg bg-primary-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-600 disabled:opacity-50"
            >
              {saveMutation.isPending ? "Saving..." : "Save"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Shared Components ────────────────────────────────────────────────

function InfoItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase text-gray-500">{label}</dt>
      <dd className="mt-1 text-sm text-gray-900">{value}</dd>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-gray-200 p-3 text-center">
      <div className="text-2xl font-bold text-gray-900">{value}</div>
      <div className="text-xs text-gray-500">{label}</div>
    </div>
  );
}

function StatsSection({
  title,
  stats,
}: {
  title: string;
  stats: Record<string, number>;
}) {
  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold text-gray-700">{title}</h3>
      <div className="grid grid-cols-3 gap-3">
        {Object.entries(stats).map(([key, value]) => (
          <StatCard
            key={key}
            label={key.replace(/_/g, " ")}
            value={value}
          />
        ))}
      </div>
    </div>
  );
}

// ── Usage Panel ──────────────────────────────────────────────────────

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(k)), units.length - 1);
  return `${(bytes / Math.pow(k, i)).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function formatNumber(n: number): string {
  return n.toLocaleString();
}

function UsagePanel() {
  const [period, setPeriod] = useState<UsagePeriod>("all");
  const { data, isLoading } = useQuery({
    queryKey: ["platform-usage", period],
    queryFn: () => fetchPlatformUsage(period),
  });

  if (isLoading || !data) {
    return (
      <div className="flex justify-center py-12">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary-500 border-t-transparent" />
      </div>
    );
  }

  const totals = data.platform;

  return (
    <div className="space-y-6">
      {/* Period toggle */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">
            Resource usage
          </h2>
          <p className="mt-1 text-sm text-gray-500">
            {period === "all"
              ? "All-time platform totals."
              : "Activity in the last 30 days."}{" "}
            Per-org breakdown lists the top 20 tenants by ticket volume.
          </p>
        </div>
        <div className="flex rounded-lg border border-gray-200 bg-white p-0.5">
          {(["all", "month"] as UsagePeriod[]).map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={clsx(
                "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                period === p
                  ? "bg-primary-50 text-primary-700"
                  : "text-gray-500 hover:text-gray-700",
              )}
            >
              {p === "all" ? "All time" : "Last 30d"}
            </button>
          ))}
        </div>
      </div>

      {/* Platform totals */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <BigStatCard
          label="Organizations"
          value={formatNumber(totals.organizations_total)}
          sub={`${formatNumber(totals.organizations_active)} active`}
        />
        <BigStatCard
          label="Active agents"
          value={formatNumber(totals.agents_active)}
        />
        <BigStatCard
          label={period === "all" ? "Tickets" : "Tickets (30d)"}
          value={formatNumber(totals.tickets_total)}
        />
        <BigStatCard
          label={period === "all" ? "Videos" : "Videos (30d)"}
          value={formatNumber(totals.videos_total)}
          sub={`${formatNumber(totals.video_minutes)} min`}
        />
        <BigStatCard
          label="Attachment + video storage"
          value={formatBytes(totals.attachment_storage_bytes)}
        />
      </div>

      {/* Per-org table */}
      <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                Organization
              </th>
              <th className="px-4 py-2 text-right text-xs font-medium uppercase tracking-wider text-gray-500">
                Agents
              </th>
              <th className="px-4 py-2 text-right text-xs font-medium uppercase tracking-wider text-gray-500">
                Tickets
              </th>
              <th className="px-4 py-2 text-right text-xs font-medium uppercase tracking-wider text-gray-500">
                Videos
              </th>
              <th className="px-4 py-2 text-right text-xs font-medium uppercase tracking-wider text-gray-500">
                Video min
              </th>
              <th className="px-4 py-2 text-right text-xs font-medium uppercase tracking-wider text-gray-500">
                Storage
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {data.organizations.length === 0 ? (
              <tr>
                <td
                  colSpan={6}
                  className="px-4 py-8 text-center text-sm text-gray-400"
                >
                  No usage to report yet.
                </td>
              </tr>
            ) : (
              data.organizations.map((row) => (
                <tr key={row.id} className="hover:bg-gray-50">
                  <td className="whitespace-nowrap px-4 py-2">
                    <div className="font-medium text-gray-900">{row.name}</div>
                    <div className="text-xs text-gray-500">{row.slug}</div>
                  </td>
                  <td className="whitespace-nowrap px-4 py-2 text-right text-gray-700">
                    {formatNumber(row.agents)}
                  </td>
                  <td className="whitespace-nowrap px-4 py-2 text-right text-gray-700">
                    {formatNumber(row.tickets)}
                  </td>
                  <td className="whitespace-nowrap px-4 py-2 text-right text-gray-700">
                    {formatNumber(row.videos)}
                  </td>
                  <td className="whitespace-nowrap px-4 py-2 text-right text-gray-700">
                    {formatNumber(row.video_minutes)}
                  </td>
                  <td className="whitespace-nowrap px-4 py-2 text-right text-gray-700">
                    {formatBytes(row.storage_bytes)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function BigStatCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-gray-500">
        {label}
      </div>
      <div className="mt-2 text-2xl font-bold text-gray-900">{value}</div>
      {sub && <div className="mt-1 text-xs text-gray-500">{sub}</div>}
    </div>
  );
}

// ── Utils ────────────────────────────────────────────────────────────

function toSlug(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}
