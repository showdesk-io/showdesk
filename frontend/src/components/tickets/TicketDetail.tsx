/**
 * Ticket detail view — chat-style message thread with inline media
 * thumbnails, lightbox viewer, assignment sidebar, and status actions.
 */

import { useState, useRef, useEffect } from "react";
import { createPortal } from "react-dom";
import { clsx } from "clsx";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import type {
  Ticket,
  TicketAttachment,
  TicketMessage as TicketMessageType,
  VideoRecording,
  User,
  Team,
} from "@/types";
import { fetchAgents, fetchTeams } from "@/api/users";
import { uploadAttachment } from "@/api/attachments";
import {
  useAssignTicket,
  useUpdateTicket,
  useResolveTicket,
  useCloseTicket,
  useReopenTicket,
  useDeleteMessage,
} from "@/hooks/useTickets";
import { useTags, useCreateTag, useSetTicketTags } from "@/hooks/useTags";

// ── Types ────────────────────────────────────────────────────────────

interface TicketDetailProps {
  ticket: Ticket;
  onSendMessage: (body: string, messageType: string) => void;
  isSending: boolean;
}

interface LightboxState {
  url: string;
  type: "image" | "video";
}

// ── Main component ──────────────────────────────────────────────────

export function TicketDetail({
  ticket,
  onSendMessage,
  isSending,
}: TicketDetailProps) {
  const [messageBody, setMessageBody] = useState("");
  const [isInternalNote, setIsInternalNote] = useState(false);
  const [attachedFiles, setAttachedFiles] = useState<File[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [lightbox, setLightbox] = useState<LightboxState | null>(null);
  const [editingTitle, setEditingTitle] = useState(false);
  const [editingDesc, setEditingDesc] = useState(false);
  const [titleDraft, setTitleDraft] = useState(ticket.title);
  const [descDraft, setDescDraft] = useState(ticket.description);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const titleInputRef = useRef<HTMLInputElement>(null);
  const descInputRef = useRef<HTMLTextAreaElement>(null);
  const queryClient = useQueryClient();
  const deleteMutation = useDeleteMessage(ticket.id);
  const updateTicketMutation = useUpdateTicket();

  // Sync drafts when ticket data changes externally
  useEffect(() => { setTitleDraft(ticket.title); }, [ticket.title]);
  useEffect(() => { setDescDraft(ticket.description); }, [ticket.description]);

  // Auto-focus on edit
  useEffect(() => { if (editingTitle) titleInputRef.current?.focus(); }, [editingTitle]);
  useEffect(() => { if (editingDesc) descInputRef.current?.focus(); }, [editingDesc]);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    if (threadRef.current) {
      threadRef.current.scrollTop = threadRef.current.scrollHeight;
    }
  }, [ticket.messages.length]);

  const saveTitle = () => {
    setEditingTitle(false);
    if (titleDraft.trim() && titleDraft.trim() !== ticket.title) {
      updateTicketMutation.mutate(
        { ticketId: ticket.id, title: titleDraft.trim() } as Parameters<typeof updateTicketMutation.mutate>[0],
        { onError: () => { toast.error("Failed to update title."); setTitleDraft(ticket.title); } },
      );
    } else { setTitleDraft(ticket.title); }
  };

  const saveDesc = () => {
    setEditingDesc(false);
    if (descDraft !== ticket.description) {
      updateTicketMutation.mutate(
        { ticketId: ticket.id, description: descDraft } as Parameters<typeof updateTicketMutation.mutate>[0],
        { onError: () => { toast.error("Failed to update description."); setDescDraft(ticket.description); } },
      );
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!messageBody.trim() && attachedFiles.length === 0) return;

    if (messageBody.trim()) {
      onSendMessage(messageBody, isInternalNote ? "internal_note" : "reply");
      setMessageBody("");
    }

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
        void queryClient.invalidateQueries({
          queryKey: ["ticket", ticket.id],
        });
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
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const removeFile = (index: number) => {
    setAttachedFiles((prev) => prev.filter((_, i) => i !== index));
  };

  // Only show initial bubble for legacy tickets (no messages but has description/videos)
  const hasMessages = ticket.messages.length > 0;
  const hasVideoMessages = ticket.messages.some((m) => m.body_type === "video");
  const initialVideos = hasVideoMessages ? [] : (ticket.videos ?? []);
  const showInitialBubble = !hasMessages && !!(ticket.description || initialVideos.length > 0);

  return (
    <div className="flex h-full">
      {/* Main thread */}
      <div className="flex flex-1 flex-col">
        {/* Header */}
        <div className="border-b border-gray-200 px-6 py-3">
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm text-gray-400">
              {ticket.reference}
            </span>
            {editingTitle ? (
              <input
                ref={titleInputRef}
                value={titleDraft}
                onChange={(e) => setTitleDraft(e.target.value)}
                onBlur={saveTitle}
                onKeyDown={(e) => {
                  if (e.key === "Enter") saveTitle();
                  if (e.key === "Escape") { setTitleDraft(ticket.title); setEditingTitle(false); }
                }}
                className="flex-1 rounded border border-primary-300 px-2 py-0.5 text-lg font-semibold text-gray-900 focus:outline-none focus:ring-1 focus:ring-primary-500"
              />
            ) : (
              <h1
                onClick={() => setEditingTitle(true)}
                className="cursor-pointer rounded px-1 text-lg font-semibold text-gray-900 hover:bg-gray-100"
              >
                {ticket.title}
              </h1>
            )}
            <IssueTypeBadge type={ticket.issue_type} />
          </div>
          {editingDesc ? (
            <textarea
              ref={descInputRef}
              value={descDraft}
              onChange={(e) => setDescDraft(e.target.value)}
              onBlur={saveDesc}
              onKeyDown={(e) => {
                if (e.key === "Escape") { setDescDraft(ticket.description); setEditingDesc(false); }
              }}
              className="mt-1 w-full resize-none rounded border border-primary-300 px-2 py-1 text-sm text-gray-600 focus:outline-none focus:ring-1 focus:ring-primary-500"
              rows={2}
            />
          ) : ticket.description ? (
            <p
              onClick={() => setEditingDesc(true)}
              className="mt-1 cursor-pointer rounded px-1 text-sm text-gray-600 hover:bg-gray-100"
            >
              {ticket.description}
            </p>
          ) : (
            <p
              onClick={() => setEditingDesc(true)}
              className="mt-1 cursor-pointer rounded px-1 text-sm text-gray-400 hover:bg-gray-100"
            >
              Add description...
            </p>
          )}
        </div>

        {/* Chat thread */}
        <div ref={threadRef} className="flex-1 overflow-auto px-6 py-4">
          {/* Initial submission (legacy tickets only) */}
          {showInitialBubble && (
            <ChatBubble
              senderName={
                ticket.requester_detail
                  ? `${ticket.requester_detail.first_name} ${ticket.requester_detail.last_name}`.trim()
                  : ticket.requester_name || "User"
              }
              senderType="user"
              timestamp={ticket.created_at}
              body={ticket.description}
              isInternal={false}
              videos={initialVideos}
              attachments={[]}
              onOpenLightbox={setLightbox}
            />
          )}

          {!hasMessages && !showInitialBubble && (
            <p className="py-8 text-center text-sm text-gray-400">
              No messages yet.
            </p>
          )}

          {ticket.messages.map((message) => (
            <ChatBubble
              key={message.id}
              messageId={message.id}
              senderName={getSenderName(message)}
              senderType={
                message.sender_type ||
                (message.author_detail ? "agent" : "user")
              }
              timestamp={message.created_at}
              body={message.body}
              isInternal={message.message_type === "internal_note"}
              attachments={message.attachments}
              videos={[]}
              onOpenLightbox={setLightbox}
              onDelete={(id) => {
                deleteMutation.mutate(id, {
                  onSuccess: () => toast.success("Message deleted."),
                  onError: () => toast.error("Failed to delete message."),
                });
              }}
            />
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
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                e.preventDefault();
                void handleSubmit(e);
              }
            }}
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
                  <PaperclipIcon />
                  <span className="max-w-[150px] truncate">{file.name}</span>
                  <span className="text-gray-400">
                    ({formatFileSize(file.size)})
                  </span>
                  <button
                    type="button"
                    onClick={() => removeFile(i)}
                    className="ml-1 text-gray-400 hover:text-red-500"
                  >
                    <XIcon size={14} />
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
                <PaperclipIcon />
                Attach
              </button>
            </div>
            <button
              type="submit"
              disabled={
                isSending ||
                isUploading ||
                (!messageBody.trim() && attachedFiles.length === 0)
              }
              className="rounded-lg bg-primary-500 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-600 disabled:opacity-50"
            >
              {isUploading
                ? "Uploading..."
                : isSending
                  ? "Sending..."
                  : "Send"}
            </button>
          </div>
        </form>
      </div>

      {/* Context sidebar */}
      <TicketSidebar ticket={ticket} />

      {/* Media lightbox */}
      {lightbox && (
        <MediaLightbox
          url={lightbox.url}
          type={lightbox.type}
          onClose={() => setLightbox(null)}
        />
      )}
    </div>
  );
}

// ── Chat bubble ─────────────────────────────────────────────────────

interface ChatBubbleProps {
  messageId?: string;
  senderName: string;
  senderType: string;
  timestamp: string;
  body: string;
  isInternal: boolean;
  attachments: TicketAttachment[];
  videos: VideoRecording[];
  onOpenLightbox: (state: LightboxState) => void;
  onDelete?: (messageId: string) => void;
}

function ChatBubble({
  messageId,
  senderName,
  senderType,
  timestamp,
  body,
  isInternal,
  attachments,
  videos,
  onOpenLightbox,
  onDelete,
}: ChatBubbleProps) {
  const isAgent = senderType === "agent";
  const initials = getInitials(senderName);

  const imageAttachments = attachments.filter((a) =>
    a.content_type.startsWith("image/"),
  );
  const videoAttachments = attachments.filter((a) =>
    a.content_type.startsWith("video/"),
  );
  const fileAttachments = attachments.filter(
    (a) =>
      !a.content_type.startsWith("image/") &&
      !a.content_type.startsWith("video/"),
  );

  const hasBody = !!(body && body.trim());
  const hasMedia =
    imageAttachments.length > 0 ||
    videoAttachments.length > 0 ||
    videos.length > 0;

  return (
    <div className={clsx("group/bubble flex gap-3 py-2", isAgent && "flex-row-reverse")}>
      {/* Avatar */}
      <div
        className={clsx(
          "flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white",
          isAgent ? "bg-indigo-500" : "bg-emerald-500",
        )}
      >
        {initials}
      </div>

      {/* Content */}
      <div className={clsx("min-w-0 flex-1", isAgent && "flex flex-col items-end")}>
        {/* Header: name + badges + time + delete */}
        <div className={clsx("mb-1 flex items-center gap-2", isAgent && "flex-row-reverse")}>
          <span className="text-sm font-medium text-gray-900">
            {senderName}
          </span>
          {isInternal && (
            <span className="flex items-center gap-0.5 rounded bg-yellow-200 px-1.5 py-0.5 text-[10px] font-medium text-yellow-800">
              <LockIcon /> Internal
            </span>
          )}
          <span className="group/time cursor-default text-xs text-gray-400">
            <span className="group-hover/time:hidden">{relativeTime(timestamp)}</span>
            <span className="hidden group-hover/time:inline">{new Date(timestamp).toLocaleString()}</span>
          </span>
          {messageId && onDelete && (
            <button
              onClick={() => {
                if (window.confirm("Delete this message?")) {
                  onDelete(messageId);
                }
              }}
              className="text-gray-400 opacity-0 transition-opacity hover:text-red-500 group-hover/bubble:opacity-100"
              title="Delete"
            >
              <TrashIcon />
            </button>
          )}
        </div>

        {/* Bubble */}
        <div
          className={clsx(
            "inline-block max-w-[85%] rounded-lg px-3.5 py-2.5",
            isInternal
              ? "border border-yellow-200 bg-yellow-50"
              : isAgent
                ? "border border-indigo-100 bg-indigo-50"
                : "border border-gray-200 bg-white",
          )}
        >
          {/* Text */}
          {hasBody && (
            <p className="whitespace-pre-wrap text-sm text-gray-700">{body}</p>
          )}

          {/* Image attachments */}
          {imageAttachments.length > 0 && (
            <div className={clsx("flex flex-wrap gap-2", hasBody && "mt-2")}>
              {imageAttachments.map((att) => (
                <button
                  key={att.id}
                  onClick={() =>
                    onOpenLightbox({ url: att.file, type: "image" })
                  }
                  className="group relative overflow-hidden rounded-lg"
                >
                  <img
                    src={att.file}
                    alt={att.filename}
                    loading="lazy"
                    className="max-h-48 rounded-lg object-cover transition-opacity group-hover:opacity-90"
                  />
                  <div className="absolute inset-0 flex items-center justify-center bg-black/0 transition-colors group-hover:bg-black/10">
                    <ExpandIcon className="opacity-0 transition-opacity group-hover:opacity-100" />
                  </div>
                </button>
              ))}
            </div>
          )}

          {/* Video attachments (from messages) */}
          {videoAttachments.length > 0 && (
            <div
              className={clsx(
                "flex flex-wrap gap-2",
                (hasBody || imageAttachments.length > 0) && "mt-2",
              )}
            >
              {videoAttachments.map((att) => (
                <VideoThumb
                  key={att.id}
                  src={att.file}
                  onClick={() =>
                    onOpenLightbox({ url: att.file, type: "video" })
                  }
                />
              ))}
            </div>
          )}

          {/* Video recordings (from ticket) */}
          {videos.length > 0 && (
            <div
              className={clsx(
                "flex flex-wrap gap-2",
                (hasBody ||
                  imageAttachments.length > 0 ||
                  videoAttachments.length > 0) &&
                  "mt-2",
              )}
            >
              {videos.map((video) => (
                <RecordingThumb
                  key={video.id}
                  video={video}
                  onClick={() => {
                    const url = video.processed_file || video.original_file;
                    if (url) onOpenLightbox({ url, type: "video" });
                  }}
                />
              ))}
            </div>
          )}

          {/* File attachments */}
          {fileAttachments.length > 0 && (
            <div
              className={clsx("flex flex-wrap gap-1.5", hasMedia && "mt-2")}
            >
              {fileAttachments.map((att) => (
                <a
                  key={att.id}
                  href={att.file}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1.5 rounded-md border border-gray-200 bg-gray-50 px-2 py-1 text-xs text-gray-600 hover:bg-gray-100"
                >
                  <PaperclipIcon />
                  <span className="max-w-[150px] truncate">
                    {att.filename}
                  </span>
                  <span className="text-gray-400">
                    ({formatFileSize(att.file_size)})
                  </span>
                </a>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Media thumbnails ────────────────────────────────────────────────

function VideoThumb({ src, onClick }: { src: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="group relative overflow-hidden rounded-lg bg-gray-900"
    >
      <video
        src={src}
        preload="metadata"
        className="max-h-48 rounded-lg object-cover"
      />
      <div className="absolute inset-0 flex items-center justify-center bg-black/30 transition-colors group-hover:bg-black/40">
        <PlayIcon />
      </div>
    </button>
  );
}

function RecordingThumb({
  video,
  onClick,
}: {
  video: VideoRecording;
  onClick: () => void;
}) {
  if (!video.is_playable) {
    return (
      <div className="flex items-center justify-center rounded-lg bg-gray-100 px-4 py-3">
        {video.status === "processing" && (
          <div className="flex items-center gap-2 text-xs text-gray-500">
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary-500 border-t-transparent" />
            Processing...
          </div>
        )}
        {video.status === "failed" && (
          <span className="text-xs text-red-500">Processing failed</span>
        )}
        {video.status === "expired" && (
          <span className="text-xs text-gray-400">Video expired</span>
        )}
      </div>
    );
  }

  return (
    <button
      onClick={onClick}
      className="group relative overflow-hidden rounded-lg bg-gray-900"
    >
      {video.thumbnail ? (
        <img
          src={video.thumbnail}
          alt="Video recording"
          className="max-h-48 rounded-lg object-cover"
        />
      ) : (
        <video
          src={video.processed_file || video.original_file}
          preload="metadata"
          className="max-h-48 rounded-lg object-cover"
        />
      )}
      <div className="absolute inset-0 flex items-center justify-center bg-black/30 transition-colors group-hover:bg-black/40">
        <PlayIcon />
      </div>
      {video.duration_seconds != null && (
        <span className="absolute bottom-2 right-2 rounded bg-black/70 px-1.5 py-0.5 text-xs text-white">
          {formatDuration(video.duration_seconds)}
        </span>
      )}
    </button>
  );
}

// ── Media lightbox ──────────────────────────────────────────────────

function MediaLightbox({
  url,
  type,
  onClose,
}: {
  url: string;
  type: "image" | "video";
  onClose: () => void;
}) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80"
      onClick={onClose}
    >
      <div
        className="relative max-h-[90vh] max-w-[90vw]"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          className="absolute -right-2 -top-10 flex h-8 w-8 items-center justify-center rounded-full text-white/80 hover:text-white"
        >
          <XIcon size={20} />
        </button>

        {type === "image" && (
          <img
            src={url}
            alt="Preview"
            className="max-h-[85vh] max-w-[90vw] rounded-lg object-contain"
          />
        )}
        {type === "video" && (
          <video
            src={url}
            controls
            autoPlay
            className="max-h-[85vh] max-w-[90vw] rounded-lg"
          >
            <track kind="captions" />
          </video>
        )}
      </div>
    </div>,
    document.body,
  );
}

// ── Sidebar ─────────────────────────────────────────────────────────

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
  const updateMutation = useUpdateTicket();
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

  const handlePriorityChange = (priority: string) => {
    updateMutation.mutate(
      { ticketId: ticket.id, priority },
      {
        onSuccess: () => toast.success("Priority updated."),
        onError: () => toast.error("Failed to update priority."),
      },
    );
  };

  const isResolved = ticket.status === "resolved";
  const isClosed = ticket.status === "closed";

  return (
    <aside className="w-80 overflow-auto border-l border-gray-200 bg-gray-50 p-6">
      {/* Status */}
      <h2 className="mb-2 text-sm font-semibold text-gray-900">Status</h2>
      <div className="mb-4 flex flex-wrap gap-1.5">
        {STATUS_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            onClick={() => {
              if (opt.value === ticket.status) return;
              if (opt.value === "resolved")
                resolveMutation.mutate(ticket.id, {
                  onSuccess: () => toast.success("Ticket resolved."),
                  onError: () => toast.error("Failed to resolve."),
                });
              else if (opt.value === "closed")
                closeMutation.mutate(ticket.id, {
                  onSuccess: () => toast.success("Ticket closed."),
                  onError: () => toast.error("Failed to close."),
                });
              else if (
                (isResolved || isClosed) &&
                (opt.value === "open" || opt.value === "in_progress")
              )
                reopenMutation.mutate(ticket.id, {
                  onSuccess: () => toast.success("Ticket reopened."),
                  onError: () => toast.error("Failed to reopen."),
                });
              else
                updateMutation.mutate(
                  { ticketId: ticket.id, status: opt.value } as Parameters<typeof updateMutation.mutate>[0],
                  {
                    onSuccess: () => toast.success(`Status: ${opt.label}.`),
                    onError: () => toast.error("Failed to update status."),
                  },
                );
            }}
            className={clsx(
              "rounded-full px-2.5 py-1 text-xs font-medium transition-colors",
              ticket.status === opt.value
                ? opt.activeClass
                : "bg-gray-100 text-gray-500 hover:bg-gray-200",
            )}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* Priority */}
      <h2 className="mb-2 text-sm font-semibold text-gray-900">Priority</h2>
      <div className="mb-4 flex flex-wrap gap-1.5">
        {PRIORITY_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            onClick={() => {
              if (opt.value !== ticket.priority) handlePriorityChange(opt.value);
            }}
            className={clsx(
              "rounded-full px-2.5 py-1 text-xs font-medium transition-colors",
              ticket.priority === opt.value
                ? opt.activeClass
                : "bg-gray-100 text-gray-500 hover:bg-gray-200",
            )}
          >
            {opt.label}
          </button>
        ))}
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
            <div className="max-h-48 space-y-1.5 overflow-y-auto">
              {ticket.context_metadata.console_errors.map((entry, i) => (
                <div
                  key={i}
                  className="rounded bg-gray-50 p-2 font-mono text-xs"
                >
                  <span
                    className={
                      entry.level === "error"
                        ? "text-red-600"
                        : "text-amber-600"
                    }
                  >
                    {entry.level === "error" ? "\u2715" : "\u26A0"}{" "}
                    {entry.message}
                  </span>
                  {entry.source && (
                    <div className="mt-0.5 text-[10px] text-gray-400">
                      {entry.source}
                    </div>
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
            <div className="max-h-48 space-y-1.5 overflow-y-auto">
              {ticket.context_metadata.network_errors.map((entry, i) => (
                <div
                  key={i}
                  className="rounded bg-gray-50 p-2 font-mono text-xs"
                >
                  <span className="text-red-600">
                    {entry.status} {entry.method} {entry.url}
                  </span>
                  <div className="mt-0.5 text-[10px] text-gray-400">
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

// ── Tag Picker ──────────────────────────────────────────────────────

const TAG_QUICK_COLORS = [
  "#EF4444",
  "#F97316",
  "#EAB308",
  "#22C55E",
  "#3B82F6",
  "#8B5CF6",
  "#EC4899",
  "#14B8A6",
  "#6366F1",
  "#6B7280",
];

function randomTagColor(): string {
  return (
    TAG_QUICK_COLORS[Math.floor(Math.random() * TAG_QUICK_COLORS.length)] ??
    "#6B7280"
  );
}

function TicketTagPicker({ ticket }: { ticket: Ticket }) {
  const { data: allTags } = useTags();
  const setTagsMutation = useSetTicketTags(ticket.id);
  const createTagMutation = useCreateTag();
  const [focused, setFocused] = useState(false);
  const [search, setSearch] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const currentTagIds = ticket.tags_detail.map((t) => t.id);

  const filteredTags = search.trim()
    ? (allTags ?? []).filter(
        (t) =>
          t.name.toLowerCase().includes(search.toLowerCase()) &&
          !currentTagIds.includes(t.id),
      )
    : [];
  const exactMatch = (allTags ?? []).some(
    (t) => t.name.toLowerCase() === search.trim().toLowerCase(),
  );

  const addTag = (tagId: string) => {
    if (currentTagIds.includes(tagId)) return;
    setTagsMutation.mutate([...currentTagIds, tagId], {
      onError: () => toast.error("Failed to update tags."),
    });
    setSearch("");
    inputRef.current?.focus();
  };

  const removeTag = (tagId: string) => {
    setTagsMutation.mutate(
      currentTagIds.filter((id) => id !== tagId),
      { onError: () => toast.error("Failed to update tags.") },
    );
  };

  const handleCreateTag = () => {
    const name = search.trim();
    if (!name) return;
    createTagMutation.mutate(
      { name, color: randomTagColor() },
      {
        onSuccess: (newTag) => {
          setTagsMutation.mutate([...currentTagIds, newTag.id], {
            onError: () => toast.error("Failed to assign tag."),
          });
          setSearch("");
          inputRef.current?.focus();
        },
        onError: () => toast.error("Failed to create tag."),
      },
    );
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && search.trim()) {
      e.preventDefault();
      // If there's a matching unselected tag, add it
      if (filteredTags.length > 0) {
        addTag(filteredTags[0]!.id);
      } else if (!exactMatch) {
        handleCreateTag();
      }
    }
    // Backspace on empty input removes last tag
    if (e.key === "Backspace" && !search && currentTagIds.length > 0) {
      removeTag(currentTagIds[currentTagIds.length - 1]!);
    }
  };

  return (
    <div className="group/tags mt-4">
      <h2 className="mb-2 text-sm font-semibold text-gray-900">Tags</h2>

      {/* Tags + inline input */}
      <div className="flex flex-wrap items-center gap-1">
        {ticket.tags_detail.map((tag) => (
          <span
            key={tag.id}
            className="group/tag flex items-center gap-0.5 rounded-full px-2 py-0.5 text-xs font-medium"
            style={{
              backgroundColor: tag.color + "20",
              color: tag.color,
            }}
          >
            {tag.name}
            <button
              onClick={() => removeTag(tag.id)}
              className="ml-0.5 opacity-0 transition-opacity hover:opacity-100 group-hover/tag:opacity-60"
            >
              <XIcon size={10} />
            </button>
          </span>
        ))}

        {/* Input appears on hover or when focused */}
        <input
          ref={inputRef}
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => { setTimeout(() => { setFocused(false); setSearch(""); }, 150); }}
          onKeyDown={handleKeyDown}
          placeholder="Add tag..."
          className={clsx(
            "w-20 rounded border-none bg-transparent px-1 py-0.5 text-xs text-gray-600 placeholder-gray-300 focus:outline-none focus:placeholder-gray-400",
            !focused && "opacity-0 group-hover/tags:opacity-100",
          )}
        />
      </div>

      {/* Dropdown suggestions */}
      {focused && search.trim() && (
        <div className="mt-1 max-h-36 overflow-auto rounded-lg border border-gray-200 bg-white shadow-sm">
          {filteredTags.map((tag) => (
            <button
              key={tag.id}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => addTag(tag.id)}
              className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs transition-colors hover:bg-gray-50"
            >
              <span
                className="h-2.5 w-2.5 rounded-full"
                style={{ backgroundColor: tag.color }}
              />
              <span className="text-gray-700">{tag.name}</span>
            </button>
          ))}
          {!exactMatch && search.trim() && (
            <button
              onMouseDown={(e) => e.preventDefault()}
              onClick={handleCreateTag}
              disabled={createTagMutation.isPending}
              className="flex w-full items-center gap-2 border-t border-gray-100 px-3 py-1.5 text-xs text-primary-600 hover:bg-primary-50"
            >
              <span>{createTagMutation.isPending ? "Creating..." : `Create "${search.trim()}"`}</span>
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ── Collapsible Section ─────────────────────────────────────────────

function CollapsibleSection({
  title,
  defaultOpen = false,
  children,
}: {
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
        <span className={`transition-transform ${open ? "rotate-90" : ""}`}>
          {"\u25B6"}
        </span>
        {title}
      </button>
      {open && <div className="mt-1.5">{children}</div>}
    </div>
  );
}

// ── Label helpers ───────────────────────────────────────────────────

function IssueTypeBadge({ type }: { type: string }) {
  const config: Record<string, { bg: string; label: string }> = {
    bug: { bg: "bg-red-100 text-red-700", label: "Bug" },
    question: { bg: "bg-blue-100 text-blue-700", label: "Question" },
    suggestion: { bg: "bg-green-100 text-green-700", label: "Suggestion" },
  };
  const c = config[type];
  if (!c) return null;
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${c.bg}`}
    >
      {c.label}
    </span>
  );
}

// ── Icons ───────────────────────────────────────────────────────────

function PlayIcon() {
  return (
    <svg
      className="h-10 w-10 text-white drop-shadow"
      fill="currentColor"
      viewBox="0 0 24 24"
    >
      <path d="M8 5v14l11-7z" />
    </svg>
  );
}

function ExpandIcon({ className }: { className?: string }) {
  return (
    <svg
      className={clsx("h-5 w-5 text-white drop-shadow", className)}
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4"
      />
    </svg>
  );
}

function LockIcon() {
  return (
    <svg
      className="h-3 w-3"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"
      />
    </svg>
  );
}

function PaperclipIcon() {
  return (
    <svg
      className="h-3.5 w-3.5 text-gray-400"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"
      />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg
      className="h-3.5 w-3.5"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
      />
    </svg>
  );
}

function XIcon({ size = 14 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M6 18L18 6M6 6l12 12"
      />
    </svg>
  );
}

// ── Status & Priority options ───────────────────────────────────────

const STATUS_OPTIONS = [
  { value: "open", label: "Open", activeClass: "bg-blue-100 text-blue-700" },
  { value: "in_progress", label: "In Progress", activeClass: "bg-yellow-100 text-yellow-700" },
  { value: "waiting", label: "Waiting", activeClass: "bg-gray-200 text-gray-700" },
  { value: "resolved", label: "Resolved", activeClass: "bg-green-100 text-green-700" },
  { value: "closed", label: "Closed", activeClass: "bg-gray-300 text-gray-600" },
];

const PRIORITY_OPTIONS = [
  { value: "low", label: "Low", activeClass: "bg-gray-200 text-gray-700" },
  { value: "medium", label: "Medium", activeClass: "bg-blue-100 text-blue-700" },
  { value: "high", label: "High", activeClass: "bg-orange-100 text-orange-700" },
  { value: "urgent", label: "Urgent", activeClass: "bg-red-100 text-red-700" },
];

// ── Utility functions ───────────────────────────────────────────────

function relativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(dateStr).toLocaleDateString();
}

function getInitials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2)
    return (parts[0]!.charAt(0) + parts[parts.length - 1]!.charAt(0)).toUpperCase();
  if (parts.length === 1) return parts[0]!.charAt(0).toUpperCase();
  return "?";
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function getSenderName(message: TicketMessageType): string {
  if (message.sender_name) return message.sender_name;
  if (message.author_detail) {
    const name =
      `${message.author_detail.first_name} ${message.author_detail.last_name}`.trim();
    return name || message.author_detail.email;
  }
  return "Unknown";
}
