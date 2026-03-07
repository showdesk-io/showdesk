/**
 * Ticket list page with filtering capabilities.
 *
 * Fast for agents: keyboard-friendly filters, dense layout,
 * instant navigation.
 */

import { useState } from "react";
import { TicketList } from "@/components/tickets/TicketList";
import { useTickets } from "@/hooks/useTickets";
import type { TicketStatus, TicketPriority } from "@/types";

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

export function TicketListPage() {
  const [statusFilter, setStatusFilter] = useState("");
  const [priorityFilter, setPriorityFilter] = useState("");
  const [searchQuery, setSearchQuery] = useState("");

  const { data, isLoading } = useTickets({
    status: statusFilter || undefined,
    priority: priorityFilter || undefined,
    search: searchQuery || undefined,
  });

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="border-b border-gray-200 bg-white px-6 py-4">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-bold text-gray-900">Tickets</h1>
          <span className="text-sm text-gray-500">
            {data?.count ?? 0} tickets
          </span>
        </div>

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
        </div>
      </div>

      {/* Ticket list */}
      <div className="flex-1 overflow-auto bg-white">
        <TicketList tickets={data?.results ?? []} isLoading={isLoading} />
      </div>
    </div>
  );
}
