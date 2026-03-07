/**
 * Ticket detail view with message thread and video player.
 *
 * Empathy by design: prominent video display, requester context
 * sidebar, emotional cues from webcam recordings.
 */

import { useState } from "react";
import { clsx } from "clsx";
import type { Ticket, TicketMessage as TicketMessageType } from "@/types";
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
      <aside className="w-80 border-l border-gray-200 bg-gray-50 p-6">
        <h2 className="mb-4 text-sm font-semibold text-gray-900">
          Requester
        </h2>
        <div className="mb-6 space-y-2 text-sm">
          <p className="text-gray-900">
            {ticket.requester_detail?.first_name}{" "}
            {ticket.requester_detail?.last_name}
          </p>
          <p className="text-gray-500">
            {ticket.requester_detail?.email ?? ticket.requester_email}
          </p>
        </div>

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

        <h2 className="mb-2 text-sm font-semibold text-gray-900">Details</h2>
        <div className="space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-gray-500">Status</span>
            <span className="font-medium">{ticket.status}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">Priority</span>
            <span className="font-medium">{ticket.priority}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">Source</span>
            <span className="font-medium">{ticket.source}</span>
          </div>
        </div>
      </aside>
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
    </div>
  );
}
