/**
 * Ticket detail view with message thread, video player, file attachments,
 * assignment, and status actions.
 */

import { useState, useRef } from "react";
import { clsx } from "clsx";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import type { Ticket, TicketAttachment, TicketMessage as TicketMessageType, User, Team } from "@/types";
import { fetchAgents, fetchTeams } from "@/api/users";
import { uploadAttachment } from "@/api/attachments";
import {
  useAssignTicket,
  useResolveTicket,
  useCloseTicket,
  useReopenTicket,
} from "@/hooks/useTickets";
import { useTags, useCreateTag, useSetTicketTags } from "@/hooks/useTags";
import { VideoPlayer } from "@/components/videos/VideoPlayer";

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
  const [attachedFiles, setAttachedFiles] = useState<File[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!messageBody.trim() && attachedFiles.length === 0) return;

    // Send message first
    if (messageBody.trim()) {
      onSendMessage(
        messageBody,
        isInternalNote ? "internal_note" : "reply",
      );
      setMessageBody("");
    }

    // Upload attached files
    if (attachedFiles.length > 0) {
      setIsUploading(true);
      try {
        for (const file of attachedFiles) {
          await uploadAttachment({ ticket: ticket.id, file });
        }
        toast.success(
          `${attachedFiles.length} file${attachedFiles.length > 1 ? "s" : ""} uploaded.`,
        );
        setAttachedFiles([]);
        void queryClient.invalidateQueries({ queryKey: ["ticket", ticket.id] });
      } catch {
        toast.error("Failed to upload files.");
      } finally {
        setIsUploading(false);
      }
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    setAttachedFiles((prev) => [...prev, ...files]);
    // Reset input so same file can be selected again
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const removeFile = (index: number) => {
    setAttachedFiles((prev) => prev.filter((_, i) => i !== index));
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
            {ticket.issue_type && ticket.issue_type !== "other" && (
              <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                ticket.issue_type === "bug" ? "bg-red-100 text-red-700" :
                ticket.issue_type === "question" ? "bg-blue-100 text-blue-700" :
                ticket.issue_type === "suggestion" ? "bg-green-100 text-green-700" :
                "bg-gray-100 text-gray-700"
              }`}>
                {ticket.issue_type === "bug" ? "Bug" :
                 ticket.issue_type === "question" ? "Question" :
                 ticket.issue_type === "suggestion" ? "Suggestion" : ticket.issue_type}
              </span>
            )}
          </div>
          {ticket.description && (
            <p className="mt-2 text-sm text-gray-600">{ticket.description}</p>
          )}
        </div>

        {/* Video recordings */}
        {ticket.videos && ticket.videos.length > 0 && (
          <div className="border-b border-gray-200 px-6 py-4">
            <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-900">
              <svg className="h-4 w-4 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
              Recordings ({ticket.videos.length})
            </h2>
            <div className="space-y-3">
              {ticket.videos.map((video) => (
                <VideoPlayer key={video.id} video={video} />
              ))}
            </div>
          </div>
        )}

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

          {/* Attached files preview */}
          {attachedFiles.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-2">
              {attachedFiles.map((file, i) => (
                <div
                  key={`${file.name}-${i}`}
                  className="flex items-center gap-1.5 rounded-lg border border-gray-200 bg-gray-50 px-2.5 py-1.5 text-xs text-gray-700"
                >
                  <svg className="h-3.5 w-3.5 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
                  </svg>
                  <span className="max-w-[150px] truncate">{file.name}</span>
                  <span className="text-gray-400">
                    ({formatFileSize(file.size)})
                  </span>
                  <button
                    type="button"
                    onClick={() => removeFile(i)}
                    className="ml-1 text-gray-400 hover:text-red-500"
                  >
                    <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
              ))}
            </div>
          )}

          <div className="mt-2 flex items-center justify-between">
            <div>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                onChange={handleFileSelect}
                className="hidden"
              />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="flex items-center gap-1 rounded-lg border border-gray-300 px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-50"
                title="Attach files"
              >
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
                </svg>
                Attach
              </button>
            </div>
            <button
              type="submit"
              disabled={isSending || isUploading || (!messageBody.trim() && attachedFiles.length === 0)}
              className="rounded-lg bg-primary-500 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-600 disabled:opacity-50"
            >
              {isUploading ? "Uploading..." : isSending ? "Sending..." : "Send"}
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

      {/* Console Errors */}
      {ticket.context_metadata?.console_errors &&
        ticket.context_metadata.console_errors.length > 0 && (
        <CollapsibleSection
          title={`Console Errors (${ticket.context_metadata.console_errors.length})`}
          defaultOpen={true}
        >
          <div className="space-y-1.5 max-h-48 overflow-y-auto">
            {ticket.context_metadata.console_errors.map((entry, i) => (
              <div key={i} className="rounded bg-gray-50 p-2 text-xs font-mono">
                <span className={entry.level === "error" ? "text-red-600" : "text-amber-600"}>
                  {entry.level === "error" ? "\u2715" : "\u26A0"} {entry.message}
                </span>
                {entry.source && (
                  <div className="text-gray-400 mt-0.5 text-[10px]">{entry.source}</div>
                )}
              </div>
            ))}
          </div>
        </CollapsibleSection>
      )}

      {/* Network Errors */}
      {ticket.context_metadata?.network_errors &&
        ticket.context_metadata.network_errors.length > 0 && (
        <CollapsibleSection
          title={`Network Errors (${ticket.context_metadata.network_errors.length})`}
          defaultOpen={true}
        >
          <div className="space-y-1.5 max-h-48 overflow-y-auto">
            {ticket.context_metadata.network_errors.map((entry, i) => (
              <div key={i} className="rounded bg-gray-50 p-2 text-xs font-mono">
                <span className="text-red-600">
                  {entry.status} {entry.method} {entry.url}
                </span>
                <div className="text-gray-400 mt-0.5 text-[10px]">
                  {entry.duration_ms}ms
                </div>
              </div>
            ))}
          </div>
        </CollapsibleSection>
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

/** Random color from a curated palette for quick tag creation. */
const TAG_QUICK_COLORS = [
  "#EF4444", "#F97316", "#EAB308", "#22C55E", "#3B82F6",
  "#8B5CF6", "#EC4899", "#14B8A6", "#6366F1", "#6B7280",
];

function randomTagColor(): string {
  return TAG_QUICK_COLORS[Math.floor(Math.random() * TAG_QUICK_COLORS.length)];
}

function TicketTagPicker({ ticket }: { ticket: Ticket }) {
  const { data: allTags } = useTags();
  const setTagsMutation = useSetTicketTags(ticket.id);
  const createTagMutation = useCreateTag();
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState("");

  const currentTagIds = ticket.tags_detail.map((t) => t.id);

  const filteredTags = (allTags ?? []).filter((t) =>
    t.name.toLowerCase().includes(search.toLowerCase()),
  );
  const exactMatch = (allTags ?? []).some(
    (t) => t.name.toLowerCase() === search.trim().toLowerCase(),
  );

  const toggleTag = (tagId: string) => {
    const newTagIds = currentTagIds.includes(tagId)
      ? currentTagIds.filter((id) => id !== tagId)
      : [...currentTagIds, tagId];

    setTagsMutation.mutate(newTagIds, {
      onError: () => toast.error("Failed to update tags."),
    });
  };

  const handleCreateTag = () => {
    const name = search.trim();
    if (!name) return;
    createTagMutation.mutate(
      { name, color: randomTagColor() },
      {
        onSuccess: (newTag) => {
          // Immediately assign the new tag to the ticket
          setTagsMutation.mutate([...currentTagIds, newTag.id], {
            onError: () => toast.error("Failed to assign tag."),
          });
          setSearch("");
        },
        onError: () => toast.error("Failed to create tag."),
      },
    );
  };

  return (
    <div className="mt-4">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-900">Tags</h2>
        <button
          onClick={() => {
            setIsOpen(!isOpen);
            if (isOpen) setSearch("");
          }}
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
      {isOpen && (
        <div className="mt-2 rounded-lg border border-gray-200 bg-white">
          {/* Search / filter input */}
          <div className="border-b border-gray-100 p-2">
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && search.trim() && !exactMatch) {
                  e.preventDefault();
                  handleCreateTag();
                }
              }}
              placeholder="Search or create tag..."
              className="w-full rounded border border-gray-200 px-2 py-1 text-xs focus:border-primary-400 focus:outline-none"
              autoFocus
            />
          </div>

          <div className="max-h-48 overflow-auto">
            {filteredTags.map((tag) => {
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
            })}

            {/* Create new tag option */}
            {search.trim() && !exactMatch && (
              <button
                onClick={handleCreateTag}
                disabled={createTagMutation.isPending}
                className="flex w-full items-center gap-2 border-t border-gray-100 px-3 py-2 text-sm text-primary-600 hover:bg-primary-50"
              >
                <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
                <span>
                  {createTagMutation.isPending ? "Creating..." : `Create "${search.trim()}"`}
                </span>
              </button>
            )}

            {filteredTags.length === 0 && !search.trim() && (
              <p className="px-3 py-2 text-xs text-gray-400">
                No tags yet. Type a name to create one.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Collapsible Section ───────────────────────────────────────────────

function CollapsibleSection({ title, defaultOpen = false, children }: {
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="mt-3">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 text-xs font-medium text-gray-600 hover:text-gray-900"
      >
        <span className={`transition-transform ${open ? "rotate-90" : ""}`}>{"\u25B6"}</span>
        {title}
      </button>
      {open && <div className="mt-1.5">{children}</div>}
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

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function AttachmentList({ attachments }: { attachments: TicketAttachment[] }) {
  if (attachments.length === 0) return null;

  return (
    <div className="mt-2 flex flex-wrap gap-2">
      {attachments.map((att) => (
        <a
          key={att.id}
          href={att.file}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1.5 rounded-lg border border-gray-200 bg-gray-50 px-2.5 py-1.5 text-xs text-gray-700 hover:bg-gray-100"
        >
          <svg className="h-3.5 w-3.5 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
          </svg>
          <span className="max-w-[150px] truncate">{att.filename}</span>
          <span className="text-gray-400">({formatFileSize(att.file_size)})</span>
        </a>
      ))}
    </div>
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
      <AttachmentList attachments={message.attachments} />
    </div>
  );
}
