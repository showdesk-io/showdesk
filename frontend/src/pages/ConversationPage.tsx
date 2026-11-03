/**
 * A ticket's public conversation, opened by a link mailed to its requester. No account.
 */

import { useState, type ChangeEvent, type FormEvent, type ReactNode } from "react";
import { useParams } from "react-router";
import { format } from "date-fns";
import clsx from "clsx";
import {
  ConversationError,
  type Conversation,
  type ConversationMessage,
} from "@/api/conversation";
import {
  useConversation,
  useRenewConversationLink,
  useSendConversationAttachment,
  useSendConversationMessage,
} from "@/hooks/useConversation";

const STATUS_LABELS: Record<string, string> = {
  open: "Open",
  in_progress: "In progress",
  waiting: "Waiting for your reply",
  resolved: "Resolved",
  closed: "Closed",
};

/** A colour the organization chose, if it is one: it ends up in a style. */
function safeColor(color: string): string | undefined {
  return /^#[0-9a-f]{3,8}$/i.test(color) ? color : undefined;
}

/** A link to an attachment, if it is a web one. */
function safeHref(url: string): string | undefined {
  return /^(https?:\/\/|\/(?!\/))/i.test(url) ? url : undefined;
}

function errorStatus(error: unknown): number | null {
  return error instanceof ConversationError ? error.status : null;
}

function sendErrorMessage(error: unknown): string {
  switch (errorStatus(error)) {
    case 400:
      return "This can't be sent. Files are limited to 20 MB, and some types aren't accepted.";
    case 409:
      return "This conversation is closed.";
    case 410:
      return "This link has expired. Reload the page to ask for a new one.";
    case 429:
      return "Too many messages at once. Please wait a moment and try again.";
    default:
      return "Your message couldn't be sent. Please try again.";
  }
}

function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-gray-50">
      <title>Your conversation</title>
      <meta name="robots" content="noindex" />
      {/* The link is a credential: it mustn't leak to the hosts of logos or files. */}
      <meta name="referrer" content="no-referrer" />
      <main className="mx-auto max-w-2xl px-4 py-8">{children}</main>
    </div>
  );
}

function Notice({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl bg-white p-8 text-center shadow-sm">
      <h1 className="text-lg font-semibold text-gray-900">{title}</h1>
      {children}
    </div>
  );
}

function ExpiredLink({ token }: { token: string }) {
  const renew = useRenewConversationLink(token);
  return (
    <Notice title="This link has expired">
      {renew.isSuccess ? (
        <p className="mt-3 text-sm text-gray-600">
          If this conversation is yours, a new link is on its way to your inbox.
        </p>
      ) : (
        <>
          <p className="mt-3 text-sm text-gray-600">
            We can email a new link to the address this conversation belongs to.
          </p>
          <button
            type="button"
            onClick={() => renew.mutate()}
            disabled={renew.isPending}
            className="mt-5 rounded-lg bg-primary-500 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-primary-600 disabled:opacity-50"
          >
            Send me a new link
          </button>
          {renew.isError && (
            <p role="alert" className="mt-3 text-sm text-red-600">
              {errorStatus(renew.error) === 429
                ? "Too many requests. Please try again later."
                : "Something went wrong. Please try again."}
            </p>
          )}
        </>
      )}
    </Notice>
  );
}

function MessageItem({ message }: { message: ConversationMessage }) {
  const mine = message.sender_type === "user";
  return (
    <li className={clsx("flex flex-col", mine ? "items-end" : "items-start")}>
      <div className="mb-1 text-xs text-gray-500">
        {mine ? "You" : message.sender_name || "Support"}
        {" · "}
        {format(new Date(message.created_at), "MMM d, HH:mm")}
      </div>
      <div
        className={clsx(
          "max-w-[85%] rounded-xl px-4 py-3 text-sm shadow-sm",
          mine ? "bg-gray-900 text-white" : "bg-white text-gray-900",
        )}
      >
        {message.body && <p className="whitespace-pre-wrap break-words">{message.body}</p>}
        {message.attachments.length > 0 && (
          <ul className={clsx("space-y-1", message.body && "mt-2")}>
            {message.attachments.map((attachment) => (
              <li key={attachment.id}>
                <a
                  href={safeHref(attachment.file)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline"
                >
                  {attachment.filename}
                </a>
              </li>
            ))}
          </ul>
        )}
      </div>
    </li>
  );
}

function ReplyBox({ token, color }: { token: string; color?: string }) {
  const [body, setBody] = useState("");
  const send = useSendConversationMessage(token);
  const attach = useSendConversationAttachment(token);
  const busy = send.isPending || attach.isPending;
  const failed = send.error ?? attach.error;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const text = body.trim();
    if (!text) return;
    attach.reset();
    send.mutate(text, { onSuccess: () => setBody("") });
  };

  const upload = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    send.reset();
    attach.mutate(file);
  };

  return (
    <form onSubmit={submit} className="mt-6 rounded-xl bg-white p-4 shadow-sm">
      <label htmlFor="conversation-reply" className="text-sm font-medium text-gray-700">
        Your reply
      </label>
      <textarea
        id="conversation-reply"
        value={body}
        onChange={(event) => setBody(event.target.value)}
        rows={4}
        maxLength={10000}
        className="mt-2 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-hidden focus:ring-1 focus:ring-primary-500"
      />
      {failed && (
        <p role="alert" className="mt-2 text-sm text-red-600">
          {sendErrorMessage(failed)}
        </p>
      )}
      <div className="mt-3 flex items-center justify-between">
        <label className="cursor-pointer text-sm font-medium text-gray-600 hover:text-gray-900">
          {attach.isPending ? "Uploading…" : "Attach a file"}
          <input type="file" className="sr-only" onChange={upload} disabled={busy} />
        </label>
        <button
          type="submit"
          disabled={busy || !body.trim()}
          style={color ? { backgroundColor: color } : undefined}
          className="rounded-lg bg-primary-500 px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          Send
        </button>
      </div>
    </form>
  );
}

function Thread({ token, conversation }: { token: string; conversation: Conversation }) {
  const { organization } = conversation;
  const color = safeColor(organization.color);
  const logo = safeHref(organization.logo);
  return (
    <>
      <header
        className="mb-6 flex items-center gap-3 border-b-4 pb-4"
        style={color ? { borderColor: color } : undefined}
      >
        {logo && <img src={logo} alt="" className="h-10 w-10 rounded object-contain" />}
        <span className="text-lg font-semibold text-gray-900">{organization.name}</span>
      </header>
      <h1 className="text-xl font-semibold text-gray-900">{conversation.title}</h1>
      <p className="mt-1 text-sm text-gray-500">
        {conversation.reference} · {STATUS_LABELS[conversation.status] ?? conversation.status}
      </p>
      <ol className="mt-6 space-y-4">
        {conversation.messages.map((message) => (
          <MessageItem key={message.id} message={message} />
        ))}
      </ol>
      {conversation.can_reply ? (
        <ReplyBox token={token} color={color} />
      ) : (
        <p className="mt-6 text-center text-sm text-gray-500">
          This conversation is closed.
        </p>
      )}
    </>
  );
}

export function ConversationPage() {
  const { token = "" } = useParams();
  const conversation = useConversation(token);
  const status = errorStatus(conversation.error);

  let content;
  if (status === 410) {
    content = <ExpiredLink token={token} />;
  } else if (status === 404) {
    content = (
      <Notice title="Conversation not found">
        <p className="mt-3 text-sm text-gray-600">
          Check that you opened the whole link from your email.
        </p>
      </Notice>
    );
  } else if (conversation.data) {
    content = <Thread token={token} conversation={conversation.data} />;
  } else if (conversation.isError) {
    content = (
      <Notice title="Something went wrong">
        <p className="mt-3 text-sm text-gray-600">Please try again in a moment.</p>
      </Notice>
    );
  } else {
    content = <p className="text-center text-sm text-gray-500">Loading…</p>;
  }
  return <Shell>{content}</Shell>;
}
