/**
 * Ticket list component with compact/expanded view modes and inline actions.
 *
 * Compact mode: scan-friendly single-line layout (default).
 * Expanded mode: shows description preview for quick triage.
 * Inline actions: change priority, assign agent, manage tags without leaving the page.
 */

import { useState, useRef, useEffect } from "react";
import { Link } from "react-router-dom";
import { clsx } from "clsx";
import { useQuery } from "@tanstack/react-query";
import toast from "react-hot-toast";
import type { TicketListItem, TicketStatus, Tag } from "@/types";
import { useUpdateTicket, useAssignTicket } from "@/hooks/useTickets";
import { useTags, useSetTicketTags } from "@/hooks/useTags";
import { usePriorities } from "@/hooks/usePriorities";
import { fetchAgents } from "@/api/users";

// ── Constants ─────────────────────────────────────────────────────────

export type ViewMode = "compact" | "expanded";

const statusColors: Record<TicketStatus, string> = {
  open: "bg-blue-100 text-blue-800",
  in_progress: "bg-yellow-100 text-yellow-800",
  waiting: "bg-gray-100 text-gray-800",
  resolved: "bg-green-100 text-green-800",
  closed: "bg-gray-100 text-gray-500",
};

/** Fallback colors when no custom priorities are loaded yet. */
const fallbackPriorityColors: Record<string, string> = {
  low: "#6B7280",
  medium: "#3B82F6",
  high: "#F97316",
  urgent: "#EF4444",
};

// ── Dropdown hook ─────────────────────────────────────────────────────

function useDropdown() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

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

  return { open, setOpen, ref };
}

// ── Priority Menu ─────────────────────────────────────────────────────

function PriorityMenu({ ticket }: { ticket: TicketListItem }) {
  const { open, setOpen, ref } = useDropdown();
  const updateTicket = useUpdateTicket();
  const { data: priorities } = usePriorities();

  const priorityColorMap = new Map(
    priorities?.map((p) => [p.slug, p.color]) ?? [],
  );
  const currentColor =
    priorityColorMap.get(ticket.priority) ??
    fallbackPriorityColors[ticket.priority] ??
    "#6B7280";

  const handleChange = (slug: string) => {
    if (slug === ticket.priority) {
      setOpen(false);
      return;
    }
    updateTicket.mutate(
      { ticketId: ticket.id, priority: slug },
      {
        onSuccess: () => {
          toast.success(`Priority changed to ${slug}`);
          setOpen(false);
        },
        onError: () => toast.error("Failed to update priority"),
      },
    );
  };

  return (
    <div ref={ref} className="relative">
      <button
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setOpen(!open);
        }}
        className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium transition-opacity hover:opacity-80"
        style={{ backgroundColor: currentColor + "20", color: currentColor }}
        title="Change priority"
      >
        <span
          className="inline-block h-2 w-2 rounded-full"
          style={{ backgroundColor: currentColor }}
        />
        {ticket.priority}
      </button>
      {open && (
        <div className="absolute left-0 top-full z-30 mt-1 w-36 rounded-lg border border-gray-200 bg-white py-1 shadow-lg">
          {(priorities ?? []).map((p) => (
            <button
              key={p.slug}
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                handleChange(p.slug);
              }}
              className={clsx(
                "flex w-full items-center gap-2 px-3 py-1.5 text-xs hover:bg-gray-50",
                p.slug === ticket.priority && "font-semibold",
              )}
            >
              <span
                className="inline-block h-2 w-2 rounded-full"
                style={{ backgroundColor: p.color }}
              />
              {p.name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Assign Menu ───────────────────────────────────────────────────────

function AssignMenu({ ticket }: { ticket: TicketListItem }) {
  const { open, setOpen, ref } = useDropdown();
  const assignTicket = useAssignTicket();
  const { data: agents } = useQuery({
    queryKey: ["agents"],
    queryFn: fetchAgents,
    enabled: open,
  });

  const handleAssign = (agentId: string | null) => {
    assignTicket.mutate(
      { ticketId: ticket.id, agent_id: agentId ?? undefined },
      {
        onSuccess: () => {
          toast.success(agentId ? "Ticket assigned" : "Ticket unassigned");
          setOpen(false);
        },
        onError: () => toast.error("Failed to assign ticket"),
      },
    );
  };

  const currentAgent = ticket.assigned_agent_detail;

  return (
    <div ref={ref} className="relative">
      <button
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setOpen(!open);
        }}
        className="inline-flex items-center gap-1 rounded-full border border-gray-200 px-2 py-0.5 text-xs text-gray-600 transition-colors hover:border-gray-300 hover:bg-gray-50"
        title="Assign agent"
      >
        {currentAgent ? (
          <span className="max-w-[80px] truncate">
            {currentAgent.first_name || currentAgent.email}
          </span>
        ) : (
          <span className="text-gray-400">Unassigned</span>
        )}
        <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && (
        <div className="absolute right-0 top-full z-30 mt-1 w-48 rounded-lg border border-gray-200 bg-white py-1 shadow-lg">
          <button
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              handleAssign(null);
            }}
            className="flex w-full items-center px-3 py-1.5 text-xs text-gray-500 hover:bg-gray-50"
          >
            Unassigned
          </button>
          {agents?.map((agent) => (
            <button
              key={agent.id}
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                handleAssign(agent.id);
              }}
              className={clsx(
                "flex w-full items-center px-3 py-1.5 text-xs hover:bg-gray-50",
                currentAgent?.id === agent.id && "font-semibold",
              )}
            >
              {agent.first_name} {agent.last_name}
              <span className="ml-auto text-gray-400 truncate max-w-[80px]">
                {agent.email}
              </span>
            </button>
          ))}
          {!agents && (
            <div className="px-3 py-2 text-xs text-gray-400">Loading...</div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Tags Menu ─────────────────────────────────────────────────────────

function TagsMenu({ ticket }: { ticket: TicketListItem }) {
  const { open, setOpen, ref } = useDropdown();
  const { data: allTags } = useTags();
  const setTicketTags = useSetTicketTags();

  const currentTagIds = new Set(ticket.tags_detail.map((t) => t.id));

  const handleToggleTag = (tag: Tag) => {
    const newIds = new Set(currentTagIds);
    if (newIds.has(tag.id)) {
      newIds.delete(tag.id);
    } else {
      newIds.add(tag.id);
    }
    setTicketTags.mutate(
      { ticketId: ticket.id, tagIds: Array.from(newIds) },
      {
        onError: () => toast.error("Failed to update tags"),
      },
    );
  };

  return (
    <div ref={ref} className="relative">
      <button
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setOpen(!open);
        }}
        className="inline-flex items-center gap-1 rounded-full border border-gray-200 px-2 py-0.5 text-xs text-gray-600 transition-colors hover:border-gray-300 hover:bg-gray-50"
        title="Manage tags"
      >
        <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 7h.01M7 3h5a2 2 0 011.414.586l7 7a2 2 0 010 2.828l-5 5a2 2 0 01-2.828 0l-7-7A2 2 0 013 10V5a2 2 0 012-2z" />
        </svg>
        {ticket.tags_detail.length > 0 && (
          <span>{ticket.tags_detail.length}</span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 top-full z-30 mt-1 w-48 rounded-lg border border-gray-200 bg-white py-1 shadow-lg">
          {allTags && allTags.length > 0 ? (
            allTags.map((tag) => (
              <button
                key={tag.id}
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  handleToggleTag(tag);
                }}
                className="flex w-full items-center gap-2 px-3 py-1.5 text-xs hover:bg-gray-50"
              >
                <span
                  className="inline-block h-3 w-3 rounded-full border"
                  style={{ backgroundColor: tag.color }}
                />
                <span className="flex-1 text-left">{tag.name}</span>
                {currentTagIds.has(tag.id) && (
                  <svg className="h-3 w-3 text-primary-500" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                  </svg>
                )}
              </button>
            ))
          ) : (
            <div className="px-3 py-2 text-xs text-gray-400">No tags defined</div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Inline Actions Bar ────────────────────────────────────────────────

function InlineActions({ ticket }: { ticket: TicketListItem }) {
  return (
    <div className="flex items-center gap-2" onClick={(e) => e.preventDefault()}>
      <PriorityMenu ticket={ticket} />
      <AssignMenu ticket={ticket} />
      <TagsMenu ticket={ticket} />
    </div>
  );
}

// ── Tag Badges (small inline) ─────────────────────────────────────────

function TagBadges({ tags }: { tags: Tag[] }) {
  if (tags.length === 0) return null;
  return (
    <div className="flex items-center gap-1">
      {tags.slice(0, 3).map((tag) => (
        <span
          key={tag.id}
          className="inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium text-white"
          style={{ backgroundColor: tag.color }}
        >
          {tag.name}
        </span>
      ))}
      {tags.length > 3 && (
        <span className="text-[10px] text-gray-400">+{tags.length - 3}</span>
      )}
    </div>
  );
}

// ── Compact Row ───────────────────────────────────────────────────────

function CompactRow({ ticket }: { ticket: TicketListItem }) {
  return (
    <div className="flex items-center gap-4 px-6 py-3 transition-colors hover:bg-gray-50">
      {/* Inline actions (priority is clickable) */}
      <InlineActions ticket={ticket} />

      {/* Ticket info (clickable link) */}
      <Link to={`/tickets/${ticket.id}`} className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono text-gray-400">
            {ticket.reference}
          </span>
          <h3 className="truncate text-sm font-medium text-gray-900">
            {ticket.title}
          </h3>
          <TagBadges tags={ticket.tags_detail} />
        </div>
        <p className="mt-0.5 text-xs text-gray-500">
          {ticket.requester_detail?.email ?? ticket.requester_email}
        </p>
      </Link>

      {/* Status badge */}
      <span
        className={clsx(
          "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
          statusColors[ticket.status],
        )}
      >
        {ticket.status.replace("_", " ")}
      </span>

      {/* Message count */}
      <span className="text-xs text-gray-400">
        {ticket.message_count} msg
      </span>
    </div>
  );
}

// ── Expanded Row ──────────────────────────────────────────────────────

function ExpandedRow({ ticket }: { ticket: TicketListItem }) {
  const descriptionPreview = ticket.description
    ? ticket.description.length > 160
      ? ticket.description.slice(0, 160) + "..."
      : ticket.description
    : "";

  return (
    <div className="px-6 py-4 transition-colors hover:bg-gray-50">
      <div className="flex items-start gap-4">
        {/* Inline actions */}
        <div className="pt-0.5">
          <InlineActions ticket={ticket} />
        </div>

        {/* Ticket info (clickable link) */}
        <Link to={`/tickets/${ticket.id}`} className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono text-gray-400">
              {ticket.reference}
            </span>
            <h3 className="truncate text-sm font-medium text-gray-900">
              {ticket.title}
            </h3>
            <TagBadges tags={ticket.tags_detail} />
          </div>
          {descriptionPreview && (
            <p className="mt-1 text-xs leading-relaxed text-gray-500 line-clamp-2">
              {descriptionPreview}
            </p>
          )}
          <div className="mt-1 flex items-center gap-3 text-xs text-gray-400">
            <span>{ticket.requester_detail?.email ?? ticket.requester_email}</span>
            <span>{ticket.message_count} msg</span>
          </div>
        </Link>

        {/* Status badge */}
        <span
          className={clsx(
            "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
            statusColors[ticket.status],
          )}
        >
          {ticket.status.replace("_", " ")}
        </span>
      </div>
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────

interface TicketListProps {
  tickets: TicketListItem[];
  isLoading: boolean;
  viewMode?: ViewMode;
}

export function TicketList({ tickets, isLoading, viewMode = "compact" }: TicketListProps) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary-500 border-t-transparent" />
      </div>
    );
  }

  if (tickets.length === 0) {
    return (
      <div className="py-12 text-center text-gray-500">
        No tickets found.
      </div>
    );
  }

  const Row = viewMode === "expanded" ? ExpandedRow : CompactRow;

  return (
    <div className="divide-y divide-gray-200">
      {tickets.map((ticket) => (
        <Row key={ticket.id} ticket={ticket} />
      ))}
    </div>
  );
}
