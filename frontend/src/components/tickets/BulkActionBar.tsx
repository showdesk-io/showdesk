/**
 * Floating action bar shown above the ticket list when one or more
 * tickets are selected. Issues a single bulkUpdateTickets request per
 * action -- the backend wraps them in a transaction.
 */

import { useState, useRef, useEffect } from "react";
import { clsx } from "clsx";
import type { User } from "@/types";

export interface BulkUpdatePayloadFromBar {
  status?: string;
  assigned_agent_id?: string | null;
}

interface Props {
  selectedIds: Set<string>;
  visibleCount: number;
  agents: User[];
  onSelectAllVisible: () => void;
  onClear: () => void;
  onBulkUpdate: (payload: BulkUpdatePayloadFromBar) => void;
  isPending: boolean;
}

export function BulkActionBar({
  selectedIds,
  visibleCount,
  agents,
  onSelectAllVisible,
  onClear,
  onBulkUpdate,
  isPending,
}: Props) {
  const count = selectedIds.size;
  const allVisibleSelected = count >= visibleCount && visibleCount > 0;

  return (
    <div
      role="toolbar"
      aria-label="Bulk actions"
      className="sticky bottom-4 left-1/2 z-30 mx-auto mt-4 flex w-max max-w-[calc(100%-2rem)] -translate-x-1/2 items-center gap-2 rounded-full border border-gray-200 bg-white px-3 py-2 shadow-lg"
      style={{ position: "sticky" }}
    >
      <span className="px-2 text-sm font-medium text-gray-900">
        {count} selected
      </span>
      {!allVisibleSelected && visibleCount > count && (
        <button
          type="button"
          onClick={onSelectAllVisible}
          className="rounded-full px-2.5 py-1 text-xs font-medium text-primary-600 hover:bg-primary-50"
        >
          Select all visible ({visibleCount})
        </button>
      )}

      <div className="mx-1 h-5 w-px bg-gray-200" />

      <BarButton
        label="Resolve"
        onClick={() => onBulkUpdate({ status: "resolved" })}
        disabled={isPending}
      />
      <BarButton
        label="Close"
        onClick={() => onBulkUpdate({ status: "closed" })}
        disabled={isPending}
      />
      <BarButton
        label="Reopen"
        onClick={() => onBulkUpdate({ status: "open" })}
        disabled={isPending}
      />

      <AssignMenu
        agents={agents}
        disabled={isPending}
        onAssign={(agentId) => onBulkUpdate({ assigned_agent_id: agentId })}
      />

      <div className="mx-1 h-5 w-px bg-gray-200" />

      <button
        type="button"
        onClick={onClear}
        className="rounded-full px-2.5 py-1 text-xs text-gray-500 hover:bg-gray-100 hover:text-gray-700"
      >
        Clear
      </button>
    </div>
  );
}

function BarButton({
  label,
  onClick,
  disabled,
}: {
  label: string;
  onClick: () => void;
  disabled: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="rounded-full px-3 py-1 text-xs font-medium text-gray-700 hover:bg-gray-100 hover:text-gray-900 disabled:opacity-50"
    >
      {label}
    </button>
  );
}

function AssignMenu({
  agents,
  disabled,
  onAssign,
}: {
  agents: User[];
  disabled: boolean;
  onAssign: (agentId: string | null) => void;
}) {
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

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        disabled={disabled}
        className={clsx(
          "rounded-full px-3 py-1 text-xs font-medium text-gray-700 hover:bg-gray-100 hover:text-gray-900 disabled:opacity-50",
          open && "bg-gray-100 text-gray-900",
        )}
      >
        Assign...
      </button>
      {open && (
        <div className="absolute bottom-full right-0 z-40 mb-2 max-h-64 w-56 overflow-auto rounded-lg border border-gray-200 bg-white py-1 shadow-lg">
          <button
            type="button"
            onClick={() => {
              onAssign(null);
              setOpen(false);
            }}
            className="block w-full px-3 py-1.5 text-left text-xs text-gray-500 hover:bg-gray-50"
          >
            Unassign
          </button>
          <div className="my-1 border-t border-gray-100" />
          {agents.length === 0 ? (
            <div className="px-3 py-1.5 text-xs text-gray-400">
              No agents available
            </div>
          ) : (
            agents.map((agent) => (
              <button
                key={agent.id}
                type="button"
                onClick={() => {
                  onAssign(agent.id);
                  setOpen(false);
                }}
                className="block w-full truncate px-3 py-1.5 text-left text-xs text-gray-700 hover:bg-gray-50"
              >
                {agent.first_name || agent.email}{" "}
                {agent.last_name && (
                  <span className="text-gray-500">{agent.last_name}</span>
                )}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
