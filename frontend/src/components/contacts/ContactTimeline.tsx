/**
 * A contact's tickets and notes, newest first, with the box to add a note.
 *
 * Tickets go by `updated_at`, which is what the API's cap keeps the latest of.
 * A note's body is shown as text, whatever it holds: never give it to the DOM as HTML.
 */

import { useId, useState, type FormEvent } from "react";
import { clsx } from "clsx";
import toast from "react-hot-toast";
import { TIMELINE_TICKETS_LIMIT } from "@/api/contacts";
import { parseApiError } from "@/api/errors";
import { useContactNotes, useContactTickets, useCreateContactNote } from "@/hooks/useContacts";
import type { ContactNote, TicketListItem } from "@/types";
import { formatDateTime } from "./format";
import { ListError, ListLoading } from "./ListParts";
import { TicketLine } from "./TicketLine";
import { fieldErrors } from "./formErrors";
import { useContactConflict } from "./useContactConflict";

const FILTERS = ["All", "Tickets", "Notes"] as const;
type Filter = (typeof FILTERS)[number];

type Item =
  | { kind: "ticket"; id: string; date: string; ticket: TicketListItem }
  | { kind: "note"; id: string; date: string; note: ContactNote };

export function ContactTimeline({
  contactId,
  readOnly,
}: {
  contactId: string;
  readOnly: boolean;
}) {
  const [filter, setFilter] = useState<Filter>("All");
  const tickets = useContactTickets(contactId);
  const notes = useContactNotes(contactId);

  const showTickets = filter !== "Notes";
  const showNotes = filter !== "Tickets";
  const isLoading = (showTickets && tickets.isLoading) || (showNotes && notes.isLoading);

  const items: Item[] = [
    ...(showTickets ? (tickets.data ?? []) : []).map(
      (ticket): Item => ({ kind: "ticket", id: ticket.id, date: ticket.updated_at, ticket }),
    ),
    ...(showNotes ? (notes.data ?? []) : []).map(
      (note): Item => ({ kind: "note", id: note.id, date: note.created_at, note }),
    ),
  ].sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());

  const ticketsFailed = showTickets && tickets.isError && !tickets.data;
  const notesFailed = showNotes && notes.isError && !notes.data;

  return (
    <section aria-label="Activity" className="space-y-4">
      {!readOnly && <NoteBox contactId={contactId} />}

      <div role="group" aria-label="Filter timeline" className="flex gap-1.5">
        {FILTERS.map((option) => (
          <button
            key={option}
            type="button"
            aria-pressed={filter === option}
            onClick={() => setFilter(option)}
            className={clsx(
              "rounded-full px-2.5 py-1 text-xs font-medium transition-colors",
              filter === option
                ? "bg-primary-100 text-primary-700"
                : "bg-gray-100 text-gray-500 hover:bg-gray-200",
            )}
          >
            {option}
          </button>
        ))}
      </div>

      {ticketsFailed && (
        <ListError
          message="Could not load tickets."
          onRetry={() => void tickets.refetch()}
          isRetrying={tickets.isFetching}
        />
      )}
      {notesFailed && (
        <ListError
          message="Could not load notes."
          onRetry={() => void notes.refetch()}
          isRetrying={notes.isFetching}
        />
      )}

      {isLoading ? (
        <ListLoading label="Loading timeline" />
      ) : items.length > 0 ? (
        <ul aria-label="Timeline" className="space-y-3">
          {items.map((item) => (
            <li
              key={`${item.kind}-${item.id}`}
              className="rounded-lg border border-gray-200 bg-white p-4"
            >
              {item.kind === "ticket" ? (
                <TicketLine ticket={item.ticket} />
              ) : (
                <NoteLine note={item.note} />
              )}
            </li>
          ))}
        </ul>
      ) : (
        !ticketsFailed &&
        !notesFailed && <p className="py-6 text-center text-sm text-gray-500">Nothing here yet.</p>
      )}

      {showTickets && !isLoading && tickets.data?.length === TIMELINE_TICKETS_LIMIT && (
        <p className="text-center text-xs text-gray-500">Showing the latest {TIMELINE_TICKETS_LIMIT}</p>
      )}
    </section>
  );
}

function NoteLine({ note }: { note: ContactNote }) {
  return (
    <div>
      <div className="flex items-center justify-between gap-3 text-xs text-gray-400">
        <span className="font-medium text-gray-700">{note.author_name || "Unknown author"}</span>
        <span>{formatDateTime(note.created_at)}</span>
      </div>
      <p className="mt-1 whitespace-pre-wrap break-words text-sm text-gray-900">{note.body}</p>
    </div>
  );
}

function NoteBox({ contactId }: { contactId: string }) {
  const inputId = useId();
  const errorId = useId();
  const createNote = useCreateContactNote(contactId);
  const handleConflict = useContactConflict(contactId);
  const [body, setBody] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const hasErrors = errors.length > 0;

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const text = body.trim();
    if (!text || createNote.isPending) return;
    setErrors([]);
    createNote.mutate(text, {
      onSuccess: () => setBody(""),
      onError: (error) => {
        if (handleConflict(error)) return;
        if (parseApiError(error).status === 400) setErrors(fieldErrors(error, "body"));
        else toast.error("Failed to add note.");
      },
    });
  };

  return (
    <form onSubmit={handleSubmit} className="rounded-lg border border-gray-200 bg-white p-4">
      <label htmlFor={inputId} className="mb-1 block text-sm font-semibold text-gray-900">
        Add note
      </label>
      <textarea
        id={inputId}
        rows={2}
        value={body}
        aria-invalid={hasErrors || undefined}
        aria-describedby={hasErrors ? errorId : undefined}
        onChange={(e) => setBody(e.target.value)}
        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-hidden focus:ring-1 focus:ring-primary-500"
      />
      {hasErrors && (
        <p id={errorId} className="mt-1 text-xs text-red-600">
          {errors.join(" ")}
        </p>
      )}
      <div className="mt-2 flex justify-end">
        <button
          type="submit"
          disabled={!body.trim() || createNote.isPending}
          className="rounded-lg bg-primary-500 px-4 py-2 text-sm font-medium text-white hover:bg-primary-600 disabled:opacity-50"
        >
          Add note
        </button>
      </div>
    </form>
  );
}
