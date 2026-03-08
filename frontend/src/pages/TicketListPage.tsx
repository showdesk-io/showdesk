/**
 * Ticket list page with filtering, saved views, and ticket creation.
 */

import { useState, useMemo, useRef, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { TicketList, type ViewMode } from "@/components/tickets/TicketList";
import { useTickets, useCreateTicket } from "@/hooks/useTickets";
import { fetchFilteredStats } from "@/api/tickets";
import { useTags } from "@/hooks/useTags";
import { useSavedViews, useCreateSavedView, useDeleteSavedView } from "@/hooks/useSavedViews";
import { useCurrentUser } from "@/hooks/useAuth";
import { fetchAgents, fetchTeams } from "@/api/users";
import type { TicketPriority, SavedView, SavedViewFilters } from "@/types";

const statusOptions: { value: string; label: string }[] = [
  { value: "", label: "All Statuses" },
  { value: "open", label: "Open" },
  { value: "in_progress", label: "In Progress" },
  { value: "waiting", label: "Waiting" },
  { value: "resolved", label: "Resolved" },
  { value: "closed", label: "Closed" },
];

const priorityOptions: { value: string; label: string }[] = [
  { value: "", label: "All Priorities" },
  { value: "urgent", label: "Urgent" },
  { value: "high", label: "High" },
  { value: "medium", label: "Medium" },
  { value: "low", label: "Low" },
];

// ── Helpers ────────────────────────────────────────────────────────────

/** Build a clean filters object (no empty strings). */
function buildFilters(
  status: string,
  priority: string,
  assigned_agent: string,
  assigned_team: string,
  tags: string,
  search: string,
): SavedViewFilters {
  const f: SavedViewFilters = {};
  if (status) f.status = status;
  if (priority) f.priority = priority;
  if (assigned_agent) f.assigned_agent = assigned_agent;
  if (assigned_team) f.assigned_team = assigned_team;
  if (tags) f.tags = tags;
  if (search) f.search = search;
  return f;
}

/** Check if two filter objects are equivalent. */
function filtersMatch(a: SavedViewFilters, b: SavedViewFilters): boolean {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]) as Set<keyof SavedViewFilters>;
  for (const k of keys) {
    if ((a[k] ?? "") !== (b[k] ?? "")) return false;
  }
  return true;
}

/** Check if any filter is active (non-empty). */
function hasActiveFilters(f: SavedViewFilters): boolean {
  return Object.values(f).some((v) => v !== undefined && v !== "");
}

// ── Main Component ─────────────────────────────────────────────────────

export function TicketListPage() {
  const navigate = useNavigate();
  const { data: currentUser } = useCurrentUser();
  const [statusFilter, setStatusFilter] = useState("");
  const [priorityFilter, setPriorityFilter] = useState("");
  const [agentFilter, setAgentFilter] = useState("");
  const [teamFilter, setTeamFilter] = useState("");
  const [tagFilter, setTagFilter] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [viewMode, setViewMode] = useState<ViewMode>("compact");
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showStatsModal, setShowStatsModal] = useState(false);
  const [activeViewId, setActiveViewId] = useState<string | null>(null);

  const { data: tags } = useTags();
  const { data: agents } = useQuery({ queryKey: ["agents"], queryFn: fetchAgents });
  const { data: teams } = useQuery({ queryKey: ["teams"], queryFn: fetchTeams });
  const { data: savedViews } = useSavedViews();

  const currentFilters = useMemo(
    () =>
      buildFilters(
        statusFilter,
        priorityFilter,
        agentFilter,
        teamFilter,
        tagFilter,
        searchQuery,
      ),
    [statusFilter, priorityFilter, agentFilter, teamFilter, tagFilter, searchQuery],
  );

  // Find if current filters match any existing saved view
  const matchingView = useMemo(
    () => savedViews?.find((v) => filtersMatch(v.filters, currentFilters)) ?? null,
    [savedViews, currentFilters],
  );

  // When filters change manually, deselect active view if it no longer matches
  useEffect(() => {
    if (activeViewId && matchingView?.id !== activeViewId) {
      setActiveViewId(matchingView?.id ?? null);
    }
  }, [matchingView, activeViewId]);

  const applyView = useCallback(
    (view: SavedView) => {
      if (activeViewId === view.id) {
        // Deselect: clear all filters
        setStatusFilter("");
        setPriorityFilter("");
        setAgentFilter("");
        setTeamFilter("");
        setTagFilter("");
        setSearchQuery("");
        setActiveViewId(null);
      } else {
        setStatusFilter(view.filters.status ?? "");
        setPriorityFilter(view.filters.priority ?? "");
        setAgentFilter(view.filters.assigned_agent ?? "");
        setTeamFilter(view.filters.assigned_team ?? "");
        setTagFilter(view.filters.tags ?? "");
        setSearchQuery(view.filters.search ?? "");
        setActiveViewId(view.id);
      }
    },
    [activeViewId],
  );

  const { data, isLoading } = useTickets({
    status: statusFilter || undefined,
    priority: priorityFilter || undefined,
    assigned_agent: agentFilter || undefined,
    assigned_team: teamFilter || undefined,
    tags: tagFilter || undefined,
    search: searchQuery || undefined,
  });

  const createTicket = useCreateTicket();

  const handleCreate = (formData: {
    title: string;
    description: string;
    priority: TicketPriority;
    requester_name: string;
    requester_email: string;
  }) => {
    createTicket.mutate(
      { ...formData, source: "agent" } as Parameters<typeof createTicket.mutate>[0],
      {
        onSuccess: (ticket) => {
          toast.success(`Ticket ${ticket.reference} created.`);
          setShowCreateModal(false);
          navigate(`/tickets/${ticket.id}`);
        },
        onError: () => toast.error("Failed to create ticket."),
      },
    );
  };

  // Show save button when: filters active + no matching saved view
  const showSaveButton = hasActiveFilters(currentFilters) && !matchingView;

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="border-b border-gray-200 bg-white px-6 py-4">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-bold text-gray-900">Tickets</h1>
          <div className="flex items-center gap-3">
            <span className="text-sm text-gray-500">
              {data?.count ?? 0} tickets
            </span>
            <button
              onClick={() => setShowStatsModal(true)}
              className="flex items-center gap-1.5 rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-600 transition-colors hover:bg-gray-50"
              title="View statistics for current filters"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
              </svg>
              Stats
            </button>
            {/* View mode toggle */}
            <div className="flex rounded-lg border border-gray-300">
              <button
                onClick={() => setViewMode("compact")}
                className={`px-2.5 py-1.5 text-xs font-medium transition-colors ${
                  viewMode === "compact"
                    ? "bg-gray-100 text-gray-900"
                    : "text-gray-500 hover:text-gray-700"
                } rounded-l-lg`}
                title="Compact view"
              >
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                </svg>
              </button>
              <button
                onClick={() => setViewMode("expanded")}
                className={`px-2.5 py-1.5 text-xs font-medium transition-colors ${
                  viewMode === "expanded"
                    ? "bg-gray-100 text-gray-900"
                    : "text-gray-500 hover:text-gray-700"
                } rounded-r-lg`}
                title="Expanded view"
              >
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 10h16M4 14h16M4 18h16" />
                </svg>
              </button>
            </div>
            <button
              onClick={() => setShowCreateModal(true)}
              className="rounded-lg bg-primary-500 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-600"
            >
              + New Ticket
            </button>
          </div>
        </div>

        {/* Saved views chips */}
        {savedViews && savedViews.length > 0 && (
          <SavedViewChips
            views={savedViews}
            activeViewId={activeViewId}
            currentUserId={currentUser?.id ?? ""}
            onSelect={applyView}
          />
        )}

        {/* Filters */}
        <div className="mt-3 flex items-center gap-3">
          <input
            type="search"
            placeholder="Search tickets..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-64 rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
          />
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:border-primary-500 focus:outline-none"
          >
            {statusOptions.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <select
            value={priorityFilter}
            onChange={(e) => setPriorityFilter(e.target.value)}
            className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:border-primary-500 focus:outline-none"
          >
            {priorityOptions.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <select
            value={agentFilter}
            onChange={(e) => setAgentFilter(e.target.value)}
            className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:border-primary-500 focus:outline-none"
          >
            <option value="">All Agents</option>
            {agents?.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agent.first_name && agent.last_name
                  ? `${agent.first_name} ${agent.last_name}`
                  : agent.email}
              </option>
            ))}
          </select>
          <select
            value={teamFilter}
            onChange={(e) => setTeamFilter(e.target.value)}
            className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:border-primary-500 focus:outline-none"
          >
            <option value="">All Teams</option>
            {teams?.map((team) => (
              <option key={team.id} value={team.id}>
                {team.name}
              </option>
            ))}
          </select>
          {tags && tags.length > 0 && (
            <select
              value={tagFilter}
              onChange={(e) => setTagFilter(e.target.value)}
              className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:border-primary-500 focus:outline-none"
            >
              <option value="">All Tags</option>
              {tags.map((tag) => (
                <option key={tag.id} value={tag.id}>
                  {tag.name}
                </option>
              ))}
            </select>
          )}

          {/* Save view button */}
          {showSaveButton && (
            <SaveViewButton filters={currentFilters} />
          )}
        </div>
      </div>

      {/* Ticket list */}
      <div className="flex-1 overflow-auto bg-white">
        <TicketList tickets={data?.results ?? []} isLoading={isLoading} viewMode={viewMode} />
      </div>

      {/* Create ticket modal */}
      {showCreateModal && (
        <CreateTicketModal
          onClose={() => setShowCreateModal(false)}
          onSubmit={handleCreate}
          isSubmitting={createTicket.isPending}
        />
      )}

      {/* Stats modal */}
      {showStatsModal && (
        <StatsModal
          filters={{
            status: statusFilter || undefined,
            priority: priorityFilter || undefined,
            assigned_agent: agentFilter || undefined,
            assigned_team: teamFilter || undefined,
            tags: tagFilter || undefined,
            search: searchQuery || undefined,
          }}
          onClose={() => setShowStatsModal(false)}
        />
      )}
    </div>
  );
}

// ── Saved View Chips ──────────────────────────────────────────────────

function SavedViewChips({
  views,
  activeViewId,
  currentUserId,
  onSelect,
}: {
  views: SavedView[];
  activeViewId: string | null;
  currentUserId: string;
  onSelect: (view: SavedView) => void;
}) {
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2">
      {views.map((view) => (
        <ViewChip
          key={view.id}
          view={view}
          isActive={view.id === activeViewId}
          isOwner={String(view.created_by) === currentUserId}
          onSelect={() => onSelect(view)}
        />
      ))}
    </div>
  );
}

function ViewChip({
  view,
  isActive,
  isOwner,
  onSelect,
}: {
  view: SavedView;
  isActive: boolean;
  isOwner: boolean;
  onSelect: () => void;
}) {
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const deleteMutation = useDeleteSavedView();
  const confirmRef = useRef<HTMLDivElement>(null);

  // Close confirm popover on outside click
  useEffect(() => {
    if (!showDeleteConfirm) return;
    const handler = (e: MouseEvent) => {
      if (confirmRef.current && !confirmRef.current.contains(e.target as Node)) {
        setShowDeleteConfirm(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [showDeleteConfirm]);

  const handleDelete = () => {
    deleteMutation.mutate(view.id, {
      onSuccess: () => {
        toast.success(`View "${view.name}" deleted.`);
        setShowDeleteConfirm(false);
      },
      onError: () => toast.error("Failed to delete view."),
    });
  };

  return (
    <div className="group relative">
      <button
        onClick={onSelect}
        className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-all ${
          isActive
            ? "bg-primary-500 text-white shadow-sm"
            : "border border-gray-200 bg-white text-gray-700 hover:border-gray-300 hover:bg-gray-50"
        }`}
      >
        {/* Shared icon */}
        {view.is_shared && (
          <svg
            className={`h-3 w-3 ${isActive ? "text-white/70" : "text-gray-400"}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"
            />
          </svg>
        )}
        {view.name}
      </button>

      {/* Delete button — only visible on hover, only for own views */}
      {isOwner && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            setShowDeleteConfirm(true);
          }}
          className="absolute -right-1 -top-1 flex h-4 w-4 items-center justify-center rounded-full bg-gray-200 text-gray-500 opacity-0 transition-opacity hover:bg-red-100 hover:text-red-600 group-hover:opacity-100"
          title="Delete view"
        >
          <svg className="h-2.5 w-2.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      )}

      {/* Delete confirmation popover */}
      {showDeleteConfirm && (
        <div
          ref={confirmRef}
          className="absolute left-0 top-full z-40 mt-2 w-56 rounded-lg border border-gray-200 bg-white p-3 shadow-lg"
        >
          <p className="mb-3 text-xs text-gray-600">
            Delete <span className="font-semibold">"{view.name}"</span>?
          </p>
          <div className="flex items-center justify-end gap-2">
            <button
              onClick={() => setShowDeleteConfirm(false)}
              className="rounded px-2.5 py-1 text-xs text-gray-600 hover:bg-gray-100"
            >
              Cancel
            </button>
            <button
              onClick={handleDelete}
              disabled={deleteMutation.isPending}
              className="rounded bg-red-500 px-2.5 py-1 text-xs font-medium text-white hover:bg-red-600 disabled:opacity-50"
            >
              {deleteMutation.isPending ? "Deleting..." : "Delete"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Save View Button + Popover ────────────────────────────────────────

function SaveViewButton({ filters }: { filters: SavedViewFilters }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [isShared, setIsShared] = useState(false);
  const createMutation = useCreateSavedView();
  const ref = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const handleSave = () => {
    if (!name.trim()) return;
    createMutation.mutate(
      { name: name.trim(), filters, is_shared: isShared },
      {
        onSuccess: () => {
          toast.success(`View "${name.trim()}" saved.`);
          setOpen(false);
          setName("");
          setIsShared(false);
        },
        onError: () => toast.error("Failed to save view. Name may already exist."),
      },
    );
  };

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="inline-flex items-center gap-1.5 rounded-lg border border-dashed border-primary-300 px-3 py-1.5 text-xs font-medium text-primary-600 transition-colors hover:border-primary-400 hover:bg-primary-50"
        title="Save current filters as a view"
      >
        <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4" />
        </svg>
        Save view
      </button>

      {open && (
        <div className="absolute right-0 top-full z-40 mt-2 w-64 rounded-lg border border-gray-200 bg-white p-4 shadow-lg">
          <h3 className="mb-3 text-sm font-semibold text-gray-900">Save view</h3>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSave();
            }}
            placeholder="View name..."
            className="mb-3 w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
            autoFocus
          />
          <label className="mb-3 flex cursor-pointer items-center gap-2 text-xs text-gray-600">
            <input
              type="checkbox"
              checked={isShared}
              onChange={(e) => setIsShared(e.target.checked)}
              className="rounded border-gray-300 text-primary-500 focus:ring-primary-500"
            />
            Shared with team
          </label>
          <div className="flex items-center justify-end gap-2">
            <button
              onClick={() => setOpen(false)}
              className="rounded px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-100"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={!name.trim() || createMutation.isPending}
              className="rounded bg-primary-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-600 disabled:opacity-50"
            >
              {createMutation.isPending ? "Saving..." : "Save"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Stats Modal ───────────────────────────────────────────────────────

const STATUS_LABELS: Record<string, string> = {
  open: "Open",
  in_progress: "In Progress",
  waiting: "Waiting",
  resolved: "Resolved",
  closed: "Closed",
};

const STATUS_COLORS: Record<string, string> = {
  open: "bg-blue-500",
  in_progress: "bg-yellow-500",
  waiting: "bg-gray-400",
  resolved: "bg-green-500",
  closed: "bg-gray-300",
};

const PRIORITY_LABELS: Record<string, string> = {
  urgent: "Urgent",
  high: "High",
  medium: "Medium",
  low: "Low",
};

const PRIORITY_COLORS: Record<string, string> = {
  urgent: "bg-red-500",
  high: "bg-orange-500",
  medium: "bg-blue-500",
  low: "bg-gray-400",
};

function StatsModal({
  filters,
  onClose,
}: {
  filters: Record<string, string | undefined>;
  onClose: () => void;
}) {
  const { data: stats, isLoading } = useQuery({
    queryKey: ["ticket-stats", filters],
    queryFn: () => fetchFilteredStats(filters),
  });

  const hasFilters = Object.values(filters).some((v) => v !== undefined && v !== "");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-full max-w-2xl rounded-xl bg-white shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Statistics</h2>
            {hasFilters && (
              <p className="text-xs text-gray-500">Filtered view</p>
            )}
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="px-6 py-5">
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary-500 border-t-transparent" />
            </div>
          ) : stats ? (
            <div className="space-y-6">
              {/* Top KPIs */}
              <div className="grid grid-cols-3 gap-4">
                <StatCard label="Total Tickets" value={stats.total} color="bg-primary-500" />
                <StatCard label="Unassigned" value={stats.unassigned} color="bg-orange-500" />
                <StatCard
                  label="Avg. Age"
                  value={formatAge(stats.avg_age_hours)}
                  color="bg-gray-500"
                />
              </div>

              {/* Status + Priority side by side */}
              <div className="grid grid-cols-2 gap-6">
                {/* By Status */}
                <div>
                  <h3 className="mb-3 text-sm font-semibold text-gray-900">By Status</h3>
                  <div className="space-y-2">
                    {Object.entries(STATUS_LABELS).map(([key, label]) => {
                      const count = stats.by_status[key] ?? 0;
                      const pct = stats.total > 0 ? (count / stats.total) * 100 : 0;
                      return (
                        <div key={key} className="flex items-center gap-3">
                          <span className="w-20 text-xs text-gray-600">{label}</span>
                          <div className="flex-1">
                            <div className="h-2 overflow-hidden rounded-full bg-gray-100">
                              <div
                                className={`h-full rounded-full ${STATUS_COLORS[key]}`}
                                style={{ width: `${pct}%` }}
                              />
                            </div>
                          </div>
                          <span className="w-8 text-right text-xs font-medium text-gray-700">
                            {count}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* By Priority */}
                <div>
                  <h3 className="mb-3 text-sm font-semibold text-gray-900">By Priority</h3>
                  <div className="space-y-2">
                    {Object.entries(PRIORITY_LABELS).map(([key, label]) => {
                      const count = stats.by_priority[key] ?? 0;
                      const pct = stats.total > 0 ? (count / stats.total) * 100 : 0;
                      return (
                        <div key={key} className="flex items-center gap-3">
                          <span className="w-20 text-xs text-gray-600">{label}</span>
                          <div className="flex-1">
                            <div className="h-2 overflow-hidden rounded-full bg-gray-100">
                              <div
                                className={`h-full rounded-full ${PRIORITY_COLORS[key]}`}
                                style={{ width: `${pct}%` }}
                              />
                            </div>
                          </div>
                          <span className="w-8 text-right text-xs font-medium text-gray-700">
                            {count}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>

              {/* Agent Workload */}
              {(stats.agent_workload.length > 0 || stats.unassigned > 0) && (
                <div>
                  <h3 className="mb-3 text-sm font-semibold text-gray-900">Agent Workload</h3>
                  <div className="space-y-2">
                    {stats.agent_workload.map((agent) => {
                      const pct =
                        stats.total > 0 ? (agent.count / stats.total) * 100 : 0;
                      return (
                        <div key={agent.agent_id} className="flex items-center gap-3">
                          <span className="w-32 truncate text-xs text-gray-600">
                            {agent.name}
                          </span>
                          <div className="flex-1">
                            <div className="h-2 overflow-hidden rounded-full bg-gray-100">
                              <div
                                className="h-full rounded-full bg-primary-500"
                                style={{ width: `${pct}%` }}
                              />
                            </div>
                          </div>
                          <span className="w-8 text-right text-xs font-medium text-gray-700">
                            {agent.count}
                          </span>
                        </div>
                      );
                    })}
                    {stats.unassigned > 0 && (
                      <div className="flex items-center gap-3">
                        <span className="w-32 text-xs italic text-gray-400">
                          Unassigned
                        </span>
                        <div className="flex-1">
                          <div className="h-2 overflow-hidden rounded-full bg-gray-100">
                            <div
                              className="h-full rounded-full bg-orange-400"
                              style={{
                                width: `${stats.total > 0 ? (stats.unassigned / stats.total) * 100 : 0}%`,
                              }}
                            />
                          </div>
                        </div>
                        <span className="w-8 text-right text-xs font-medium text-gray-700">
                          {stats.unassigned}
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <p className="py-8 text-center text-sm text-gray-500">
              No data available.
            </p>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end border-t border-gray-200 px-6 py-3">
          <button
            onClick={onClose}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  color,
}: {
  label: string;
  value: number | string;
  color: string;
}) {
  return (
    <div className="rounded-lg border border-gray-200 p-4">
      <div className="flex items-center gap-2">
        <div className={`h-2.5 w-2.5 rounded-full ${color}`} />
        <span className="text-xs font-medium text-gray-500">{label}</span>
      </div>
      <p className="mt-1 text-2xl font-bold text-gray-900">{value}</p>
    </div>
  );
}

function formatAge(hours: number): string {
  if (hours < 1) return "< 1h";
  if (hours < 24) return `${Math.round(hours)}h`;
  const days = Math.round(hours / 24);
  return days === 1 ? "1 day" : `${days} days`;
}

// ── Create Ticket Modal ───────────────────────────────────────────────

function CreateTicketModal({
  onClose,
  onSubmit,
  isSubmitting,
}: {
  onClose: () => void;
  onSubmit: (data: {
    title: string;
    description: string;
    priority: TicketPriority;
    requester_name: string;
    requester_email: string;
  }) => void;
  isSubmitting: boolean;
}) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState<TicketPriority>("medium");
  const [requesterName, setRequesterName] = useState("");
  const [requesterEmail, setRequesterEmail] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    onSubmit({
      title,
      description,
      priority,
      requester_name: requesterName,
      requester_email: requesterEmail,
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-full max-w-lg rounded-xl bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-gray-900">New Ticket</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4 px-6 py-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              Title *
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
              placeholder="Brief description of the issue"
              autoFocus
              required
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full resize-none rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
              rows={3}
              placeholder="Detailed description..."
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">
                Requester Name
              </label>
              <input
                type="text"
                value={requesterName}
                onChange={(e) => setRequesterName(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
                placeholder="John Doe"
              />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">
                Requester Email
              </label>
              <input
                type="email"
                value={requesterEmail}
                onChange={(e) => setRequesterEmail(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
                placeholder="john@example.com"
              />
            </div>
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              Priority
            </label>
            <select
              value={priority}
              onChange={(e) => setPriority(e.target.value as TicketPriority)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none"
            >
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
              <option value="urgent">Urgent</option>
            </select>
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
              disabled={isSubmitting || !title.trim()}
              className="rounded-lg bg-primary-500 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-600 disabled:opacity-50"
            >
              {isSubmitting ? "Creating..." : "Create Ticket"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
