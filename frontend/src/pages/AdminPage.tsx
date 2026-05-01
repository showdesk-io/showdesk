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
} from "@/api/admin";
export function AdminPage() {
  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-gray-200 bg-white px-6 pt-6">
        <h1 className="mb-4 text-2xl font-bold text-gray-900">
          Platform Admin
        </h1>
      </div>
      <div className="flex-1 overflow-auto p-6">
        <OrganizationsPanel />
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

// ── Utils ────────────────────────────────────────────────────────────

function toSlug(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}
