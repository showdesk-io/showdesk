/**
 * Dashboard page showing an overview of ticket activity.
 *
 * Fast for agents: key metrics at a glance, quick access to
 * recent tickets, and a summary of what needs attention.
 */

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { fetchOrganization, fetchTicketStats } from "@/api/users";
import { useTickets } from "@/hooks/useTickets";
import { useCurrentUser } from "@/hooks/useAuth";
import { StatusBadge, PriorityBadge } from "@/components/common/StatusBadge";

export function DashboardPage() {
  const { data: user } = useCurrentUser();
  const { data: org } = useQuery({
    queryKey: ["organization"],
    queryFn: fetchOrganization,
  });
  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ["ticketStats"],
    queryFn: fetchTicketStats,
  });
  const { data: recentTickets } = useTickets({ page: 1 });
  const showOnboardingNudge = !!org && !org.onboarding_completed_at;

  const statCards = [
    {
      label: "Open",
      value: stats?.open ?? "-",
      color: "bg-blue-500",
      link: "/tickets?status=open",
    },
    {
      label: "In Progress",
      value: stats?.in_progress ?? "-",
      color: "bg-yellow-500",
      link: "/tickets?status=in_progress",
    },
    {
      label: "Total",
      value: stats?.total ?? "-",
      color: "bg-gray-500",
      link: "/tickets",
    },
    {
      label: "Urgent",
      value: stats?.urgent ?? "-",
      color: "bg-red-500",
      link: "/tickets?priority=urgent",
    },
  ];

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">
          {user ? `Welcome back, ${user.first_name}` : "Dashboard"}
        </h1>
        <p className="text-sm text-gray-500">
          Here is what is happening with your tickets today.
        </p>
      </div>

      {showOnboardingNudge && (
        <div className="mb-6 flex items-center justify-between rounded-xl border border-primary-200 bg-primary-50 px-5 py-4">
          <div>
            <p className="text-sm font-semibold text-primary-900">
              Finish setting up your workspace
            </p>
            <p className="mt-0.5 text-xs text-primary-800">
              Customize your widget, invite teammates, and grab your embed
              snippet — just a couple of minutes.
            </p>
          </div>
          <Link
            to="/onboarding"
            className="ml-4 shrink-0 rounded-lg bg-primary-500 px-4 py-2 text-sm font-medium text-white hover:bg-primary-600"
          >
            Resume setup
          </Link>
        </div>
      )}

      {/* Stats cards */}
      <div className="mb-8 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
        {statCards.map((stat) => (
          <Link
            key={stat.label}
            to={stat.link}
            className="rounded-xl border border-gray-200 bg-white p-6 transition-shadow hover:shadow-md"
          >
            <div className="flex items-center gap-3">
              <div className={`h-3 w-3 rounded-full ${stat.color}`} />
              <span className="text-sm font-medium text-gray-500">
                {stat.label}
              </span>
            </div>
            <p className="mt-2 text-3xl font-bold text-gray-900">
              {statsLoading ? (
                <span className="inline-block h-9 w-12 animate-pulse rounded bg-gray-200" />
              ) : (
                stat.value
              )}
            </p>
          </Link>
        ))}
      </div>

      {/* Recent tickets */}
      <div className="rounded-xl border border-gray-200 bg-white">
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-gray-900">
            Recent Tickets
          </h2>
          <Link
            to="/tickets"
            className="text-sm font-medium text-primary-600 hover:text-primary-700"
          >
            View all
          </Link>
        </div>

        {recentTickets?.results.length === 0 ? (
          <div className="px-6 py-12 text-center text-gray-500">
            No tickets yet. They will appear here once submitted.
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {recentTickets?.results.slice(0, 8).map((ticket) => (
              <Link
                key={ticket.id}
                to={`/tickets/${ticket.id}`}
                className="flex items-center gap-4 px-6 py-3 transition-colors hover:bg-gray-50"
              >
                <PriorityBadge priority={ticket.priority} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs text-gray-400">
                      {ticket.reference}
                    </span>
                    <span className="truncate text-sm font-medium text-gray-900">
                      {ticket.title}
                    </span>
                  </div>
                  <p className="text-xs text-gray-500">
                    {ticket.requester_detail?.email ?? ticket.requester_email}
                    {" \u00B7 "}
                    {new Date(ticket.created_at).toLocaleDateString()}
                  </p>
                </div>
                <StatusBadge status={ticket.status} />
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
