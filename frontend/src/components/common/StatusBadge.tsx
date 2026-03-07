/**
 * Reusable status badge component.
 */

import { clsx } from "clsx";
import type { TicketPriority, TicketStatus } from "@/types";

const statusStyles: Record<TicketStatus, string> = {
  open: "bg-blue-100 text-blue-800",
  in_progress: "bg-yellow-100 text-yellow-800",
  waiting: "bg-gray-100 text-gray-800",
  resolved: "bg-green-100 text-green-800",
  closed: "bg-gray-100 text-gray-500",
};

const priorityStyles: Record<TicketPriority, string> = {
  low: "bg-gray-100 text-gray-600",
  medium: "bg-blue-100 text-blue-600",
  high: "bg-orange-100 text-orange-600",
  urgent: "bg-red-100 text-red-700",
};

interface StatusBadgeProps {
  status: TicketStatus;
}

export function StatusBadge({ status }: StatusBadgeProps) {
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize",
        statusStyles[status],
      )}
    >
      {status.replace("_", " ")}
    </span>
  );
}

interface PriorityBadgeProps {
  priority: TicketPriority;
}

export function PriorityBadge({ priority }: PriorityBadgeProps) {
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize",
        priorityStyles[priority],
      )}
    >
      {priority}
    </span>
  );
}
