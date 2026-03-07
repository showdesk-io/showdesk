/**
 * Team and agents management page.
 */

import { useQuery } from "@tanstack/react-query";
import { fetchAgents, fetchTeams } from "@/api/users";

export function TeamPage() {
  const { data: agents, isLoading: agentsLoading } = useQuery({
    queryKey: ["agents"],
    queryFn: fetchAgents,
  });
  const { data: teams, isLoading: teamsLoading } = useQuery({
    queryKey: ["teams"],
    queryFn: fetchTeams,
  });

  return (
    <div className="p-6">
      <h1 className="mb-6 text-2xl font-bold text-gray-900">Team</h1>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Agents */}
        <div className="rounded-xl border border-gray-200 bg-white">
          <div className="border-b border-gray-200 px-6 py-4">
            <h2 className="text-lg font-semibold text-gray-900">Agents</h2>
          </div>
          {agentsLoading ? (
            <div className="flex justify-center py-8">
              <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary-500 border-t-transparent" />
            </div>
          ) : (
            <div className="divide-y divide-gray-100">
              {agents?.map((agent) => (
                <div
                  key={agent.id}
                  className="flex items-center gap-4 px-6 py-4"
                >
                  <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary-100 text-sm font-semibold text-primary-700">
                    {agent.first_name.charAt(0)}
                    {agent.last_name.charAt(0)}
                  </div>
                  <div className="flex-1">
                    <p className="text-sm font-medium text-gray-900">
                      {agent.first_name} {agent.last_name}
                    </p>
                    <p className="text-xs text-gray-500">{agent.email}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <span
                      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                        agent.role === "admin"
                          ? "bg-purple-100 text-purple-700"
                          : "bg-blue-100 text-blue-700"
                      }`}
                    >
                      {agent.role}
                    </span>
                    <span
                      className={`h-2.5 w-2.5 rounded-full ${
                        agent.is_available ? "bg-green-400" : "bg-gray-300"
                      }`}
                      title={agent.is_available ? "Available" : "Unavailable"}
                    />
                  </div>
                </div>
              ))}
              {agents?.length === 0 && (
                <div className="px-6 py-8 text-center text-gray-500">
                  No agents found.
                </div>
              )}
            </div>
          )}
        </div>

        {/* Teams */}
        <div className="rounded-xl border border-gray-200 bg-white">
          <div className="border-b border-gray-200 px-6 py-4">
            <h2 className="text-lg font-semibold text-gray-900">Teams</h2>
          </div>
          {teamsLoading ? (
            <div className="flex justify-center py-8">
              <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary-500 border-t-transparent" />
            </div>
          ) : (
            <div className="divide-y divide-gray-100">
              {teams?.map((team) => (
                <div key={team.id} className="px-6 py-4">
                  <div className="flex items-center justify-between">
                    <p className="text-sm font-medium text-gray-900">
                      {team.name}
                    </p>
                    <span className="text-xs text-gray-500">
                      {team.members.length} members
                    </span>
                  </div>
                  {team.description && (
                    <p className="mt-1 text-xs text-gray-500">
                      {team.description}
                    </p>
                  )}
                  <div className="mt-2 flex -space-x-2">
                    {team.members.slice(0, 5).map((member) => (
                      <div
                        key={member.id}
                        className="flex h-7 w-7 items-center justify-center rounded-full border-2 border-white bg-primary-100 text-xs font-medium text-primary-700"
                        title={`${member.first_name} ${member.last_name}`}
                      >
                        {member.first_name.charAt(0)}
                      </div>
                    ))}
                    {team.members.length > 5 && (
                      <div className="flex h-7 w-7 items-center justify-center rounded-full border-2 border-white bg-gray-100 text-xs font-medium text-gray-600">
                        +{team.members.length - 5}
                      </div>
                    )}
                  </div>
                </div>
              ))}
              {teams?.length === 0 && (
                <div className="px-6 py-8 text-center text-gray-500">
                  No teams found.
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
