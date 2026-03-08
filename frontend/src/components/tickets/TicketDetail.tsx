/**
 * Ticket detail view with message thread, assignment, and status actions.
 */

import { useState } from "react";
import { clsx } from "clsx";
import { useQuery } from "@tanstack/react-query";
import toast from "react-hot-toast";
import type { Ticket, TicketMessage as TicketMessageType, User, Team } from "@/types";
import { fetchAgents, fetchTeams } from "@/api/users";
import {
  useAssignTicket,
  useResolveTicket,
  useCloseTicket,
  useReopenTicket,
} from "@/hooks/useTickets";
import { useTags, useSetTicketTags } from "@/hooks/useTags";

interface TicketDetailProps {
  ticket: Ticket;
  onSendMessage: (body: string, messageType: string) => void;
  isSending: boolean;
}

export function TicketDetail({
  ticket,
  onSendMessage,
  isSending,
}: TicketDetailProps) {
  const [messageBody, setMessageBody] = useState("");
  const [isInternalNote, setIsInternalNote] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!messageBody.trim()) return;
    onSendMessage(
      messageBody,
      isInternalNote ? "internal_note" : "reply",
    );
    setMessageBody("");
  };

  return (
    <div className="flex h-full">
      {/* Main thread */}
      <div className="flex flex-1 flex-col">
        {/* Header */}
        <div className="border-b border-gray-200 px-6 py-4">
          <div className="flex items-center gap-3">
            <span className="font-mono text-sm text-gray-400">
              {ticket.reference}
            </span>
            <h1 className="text-lg font-semibold text-gray-900">
              {ticket.title}
            </h1>
          </div>
          {ticket.description && (
            <p className="mt-2 text-sm text-gray-600">{ticket.description}</p>
          )}
        </div>

        {/* Messages */}
        <div className="flex-1 space-y-4 overflow-auto p-6">
          {ticket.messages.length === 0 && (
            <p className="text-center text-sm text-gray-400">
              No messages yet.
            </p>
          )}
          {ticket.messages.map((message) => (
            <MessageBubble key={message.id} message={message} />
          ))}
        </div>

        {/* Reply form */}
        <form onSubmit={handleSubmit} className="border-t border-gray-200 p-4">
          <div className="mb-2 flex items-center gap-2">
            <button
              type="button"
              onClick={() => setIsInternalNote(false)}
              className={clsx(
                "rounded-md px-3 py-1 text-xs font-medium",
                !isInternalNote
                  ? "bg-primary-100 text-primary-700"
                  : "text-gray-500 hover:text-gray-700",
              )}
            >
              Reply
            </button>
            <button
              type="button"
              onClick={() => setIsInternalNote(true)}
              className={clsx(
                "rounded-md px-3 py-1 text-xs font-medium",
                isInternalNote
                  ? "bg-yellow-100 text-yellow-700"
                  : "text-gray-500 hover:text-gray-700",
              )}
            >
              Internal Note
            </button>
          </div>
          <textarea
            value={messageBody}
            onChange={(e) => setMessageBody(e.target.value)}
            placeholder={
              isInternalNote
                ? "Write an internal note..."
                : "Write a reply..."
            }
            className="w-full resize-none rounded-lg border border-gray-300 px-4 py-3 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
            rows={3}
          />
          <div className="mt-2 flex justify-end">
            <button
              type="submit"
              disabled={isSending || !messageBody.trim()}
              className="rounded-lg bg-primary-500 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-600 disabled:opacity-50"
            >
              {isSending ? "Sending..." : "Send"}
            </button>
          </div>
        </form>
      </div>

      {/* Context sidebar */}
      <TicketSidebar ticket={ticket} />
    </div>
  );
}

// ── Sidebar with assignment + status actions ──────────────────────────

function TicketSidebar({ ticket }: { ticket: Ticket }) {
  const { data: agents } = useQuery({
    queryKey: ["agents"],
    queryFn: fetchAgents,
  });
  const { data: teams } = useQuery({
    queryKey: ["teams"],
    queryFn: fetchTeams,
  });

  const assignMutation = useAssignTicket();
  const resolveMutation = useResolveTicket();
  const closeMutation = useCloseTicket();
  const reopenMutation = useReopenTicket();

  const handleAssignAgent = (agentId: string) => {
    assignMutation.mutate(
      { ticketId: ticket.id, agent_id: agentId || undefined },
      {
        onSuccess: () => toast.success("Agent assigned."),
        onError: () => toast.error("Failed to assign agent."),
      },
    );
  };

  const handleAssignTeam = (teamId: string) => {
    assignMutation.mutate(
      { ticketId: ticket.id, team_id: teamId || undefined },
      {
        onSuccess: () => toast.success("Team assigned."),
        onError: () => toast.error("Failed to assign team."),
      },
    );
  };

  const isResolved = ticket.status === "resolved";
  const isClosed = ticket.status === "closed";
  const canResolve = !isResolved && !isClosed;
  const canClose = !isClosed;
  const canReopen = isResolved || isClosed;

  return (
    <aside className="w-80 overflow-auto border-l border-gray-200 bg-gray-50 p-6">
      {/* Status Actions */}
      <h2 className="mb-3 text-sm font-semibold text-gray-900">Actions</h2>
      <div className="mb-6 flex flex-wrap gap-2">
        {canResolve && (
          <button
            onClick={() =>
              resolveMutation.mutate(ticket.id, {
                onSuccess: () => toast.success("Ticket resolved."),
                onError: () => toast.error("Failed to resolve ticket."),
              })
            }
            disabled={resolveMutation.isPending}
            className="rounded-lg bg-green-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-green-600 disabled:opacity-50"
          >
            Resolve
          </button>
        )}
        {canClose && (
          <button
            onClick={() =>
              closeMutation.mutate(ticket.id, {
                onSuccess: () => toast.success("Ticket closed."),
                onError: () => toast.error("Failed to close ticket."),
              })
            }
            disabled={closeMutation.isPending}
            className="rounded-lg bg-gray-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-600 disabled:opacity-50"
          >
            Close
          </button>
        )}
        {canReopen && (
          <button
            onClick={() =>
              reopenMutation.mutate(ticket.id, {
                onSuccess: () => toast.success("Ticket reopened."),
                onError: () => toast.error("Failed to reopen ticket."),
              })
            }
            disabled={reopenMutation.isPending}
            className="rounded-lg bg-blue-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-600 disabled:opacity-50"
          >
            Reopen
          </button>
        )}
      </div>

      {/* Assignment */}
      <h2 className="mb-2 text-sm font-semibold text-gray-900">
        Assigned Agent
      </h2>
      <select
        value={ticket.assigned_agent ?? ""}
        onChange={(e) => handleAssignAgent(e.target.value)}
        className="mb-4 w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:border-primary-500 focus:outline-none"
      >
        <option value="">Unassigned</option>
        {agents?.map((agent: User) => (
          <option key={agent.id} value={agent.id}>
            {agent.first_name} {agent.last_name} ({agent.email})
          </option>
        ))}
      </select>

      <h2 className="mb-2 text-sm font-semibold text-gray-900">
        Assigned Team
      </h2>
      <select
        value={ticket.assigned_team ?? ""}
        onChange={(e) => handleAssignTeam(e.target.value)}
        className="mb-6 w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:border-primary-500 focus:outline-none"
      >
        <option value="">No team</option>
        {teams?.map((team: Team) => (
          <option key={team.id} value={team.id}>
            {team.name}
          </option>
        ))}
      </select>

      {/* Requester */}
      <h2 className="mb-2 text-sm font-semibold text-gray-900">Requester</h2>
      <div className="mb-6 space-y-1 text-sm">
        <p className="text-gray-900">
          {ticket.requester_detail
            ? `${ticket.requester_detail.first_name} ${ticket.requester_detail.last_name}`
            : ticket.requester_name || "Unknown"}
        </p>
        <p className="text-gray-500">
          {ticket.requester_detail?.email ?? ticket.requester_email}
        </p>
      </div>

      {/* Technical Context */}
      {ticket.context_url && (
        <>
          <h2 className="mb-2 text-sm font-semibold text-gray-900">
            Technical Context
          </h2>
          <div className="mb-6 space-y-1 text-xs text-gray-500">
            <p>
              <span className="font-medium">URL:</span> {ticket.context_url}
            </p>
            {ticket.context_browser && (
              <p>
                <span className="font-medium">Browser:</span>{" "}
                {ticket.context_browser}
              </p>
            )}
            {ticket.context_os && (
              <p>
                <span className="font-medium">OS:</span> {ticket.context_os}
              </p>
            )}
            {ticket.context_screen_resolution && (
              <p>
                <span className="font-medium">Resolution:</span>{" "}
                {ticket.context_screen_resolution}
              </p>
            )}
          </div>
        </>
      )}

      {/* Details */}
      <h2 className="mb-2 text-sm font-semibold text-gray-900">Details</h2>
      <div className="space-y-2 text-sm">
        <div className="flex justify-between">
          <span className="text-gray-500">Status</span>
          <StatusLabel status={ticket.status} />
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">Priority</span>
          <PriorityLabel priority={ticket.priority} />
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">Source</span>
          <span className="font-medium capitalize">{ticket.source}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">Created</span>
          <span className="font-medium">
            {new Date(ticket.created_at).toLocaleDateString()}
          </span>
        </div>
      </div>

      {/* Tags */}
      <TicketTagPicker ticket={ticket} />
    </aside>
  );
}

// ── Tag Picker ────────────────────────────────────────────────────────

function TicketTagPicker({ ticket }: { ticket: Ticket }) {
  const { data: allTags } = useTags();
  const setTagsMutation = useSetTicketTags(ticket.id);
  const [isOpen, setIsOpen] = useState(false);

  const currentTagIds = ticket.tags_detail.map((t) => t.id);

  const toggleTag = (tagId: string) => {
    const newTagIds = currentTagIds.includes(tagId)
      ? currentTagIds.filter((id) => id !== tagId)
      : [...currentTagIds, tagId];

    setTagsMutation.mutate(newTagIds, {
      onError: () => toast.error("Failed to update tags."),
    });
  };

  return (
    <div className="mt-4">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-900">Tags</h2>
        <button
          onClick={() => setIsOpen(!isOpen)}
          className="text-xs text-primary-600 hover:text-primary-700"
        >
          {isOpen ? "Done" : "Edit"}
        </button>
      </div>

      {/* Current tags */}
      <div className="flex flex-wrap gap-1">
        {ticket.tags_detail.length === 0 && !isOpen && (
          <span className="text-xs text-gray-400">No tags</span>
        )}
        {ticket.tags_detail.map((tag) => (
          <span
            key={tag.id}
            className="rounded-full px-2 py-0.5 text-xs font-medium"
            style={{
              backgroundColor: tag.color + "20",
              color: tag.color,
            }}
          >
            {tag.name}
          </span>
        ))}
      </div>

      {/* Tag picker dropdown */}
      {isOpen && allTags && (
        <div className="mt-2 max-h-48 overflow-auto rounded-lg border border-gray-200 bg-white">
          {allTags.length === 0 ? (
            <p className="px-3 py-2 text-xs text-gray-400">
              No tags. Create them in Settings.
            </p>
          ) : (
            allTags.map((tag) => {
              const isSelected = currentTagIds.includes(tag.id);
              return (
                <button
                  key={tag.id}
                  onClick={() => toggleTag(tag.id)}
                  className={clsx(
                    "flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm transition-colors hover:bg-gray-50",
                    isSelected && "bg-gray-50",
                  )}
                >
                  <span
                    className="h-3 w-3 rounded-full"
                    style={{ backgroundColor: tag.color }}
                  />
                  <span className="flex-1 text-gray-700">{tag.name}</span>
                  {isSelected && (
                    <svg
                      className="h-4 w-4 text-primary-500"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                      strokeWidth={2}
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M5 13l4 4L19 7"
                      />
                    </svg>
                  )}
                </button>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}

// ── Small helpers ─────────────────────────────────────────────────────

function StatusLabel({ status }: { status: string }) {
  const colors: Record<string, string> = {
    open: "text-blue-700 bg-blue-100",
    in_progress: "text-yellow-700 bg-yellow-100",
    waiting: "text-gray-700 bg-gray-100",
    resolved: "text-green-700 bg-green-100",
    closed: "text-gray-500 bg-gray-100",
  };
  return (
    <span
      className={clsx(
        "rounded-full px-2 py-0.5 text-xs font-medium",
        colors[status] ?? "text-gray-600 bg-gray-100",
      )}
    >
      {status.replace("_", " ")}
    </span>
  );
}

function PriorityLabel({ priority }: { priority: string }) {
  const colors: Record<string, string> = {
    low: "text-gray-600 bg-gray-100",
    medium: "text-blue-600 bg-blue-100",
    high: "text-orange-600 bg-orange-100",
    urgent: "text-red-600 bg-red-100",
  };
  return (
    <span
      className={clsx(
        "rounded-full px-2 py-0.5 text-xs font-medium",
        colors[priority] ?? "text-gray-600 bg-gray-100",
      )}
    >
      {priority}
    </span>
  );
}

function MessageBubble({ message }: { message: TicketMessageType }) {
  const isInternal = message.message_type === "internal_note";

  return (
    <div
      className={clsx(
        "rounded-lg border p-4",
        isInternal
          ? "border-yellow-200 bg-yellow-50"
          : "border-gray-200 bg-white",
      )}
    >
      <div className="mb-2 flex items-center justify-between">
        <span className="text-sm font-medium text-gray-900">
          {message.author_detail?.first_name ?? "System"}{" "}
          {message.author_detail?.last_name ?? ""}
        </span>
        <div className="flex items-center gap-2">
          {isInternal && (
            <span className="rounded bg-yellow-200 px-1.5 py-0.5 text-xs text-yellow-800">
              Internal
            </span>
          )}
          <span className="text-xs text-gray-400">
            {new Date(message.created_at).toLocaleString()}
          </span>
        </div>
      </div>
      <p className="whitespace-pre-wrap text-sm text-gray-700">
        {message.body}
      </p>
    </div>
  );
}
