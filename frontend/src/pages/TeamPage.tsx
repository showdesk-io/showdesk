/**
 * Team management page with CRUD operations.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { fetchAgents, fetchTeams, createTeam, deleteTeam } from "@/api/users";
import { useCurrentUser } from "@/hooks/useAuth";

export function TeamPage() {
  const queryClient = useQueryClient();
  const { data: currentUser } = useCurrentUser();
  const isAdmin = currentUser?.role === "admin";
  const { data: agents, isLoading: agentsLoading } = useQuery({
    queryKey: ["agents"],
    queryFn: fetchAgents,
  });
  const { data: teams, isLoading: teamsLoading } = useQuery({
    queryKey: ["teams"],
    queryFn: fetchTeams,
  });

  const [showCreate, setShowCreate] = useState(false);
  const [newTeamName, setNewTeamName] = useState("");
  const [newTeamDesc, setNewTeamDesc] = useState("");

  const createMutation = useMutation({
    mutationFn: createTeam,
    onSuccess: () => {
      toast.success("Team created.");
      setShowCreate(false);
      setNewTeamName("");
      setNewTeamDesc("");
      void queryClient.invalidateQueries({ queryKey: ["teams"] });
    },
    onError: () => toast.error("Failed to create team."),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteTeam,
    onSuccess: () => {
      toast.success("Team deleted.");
      void queryClient.invalidateQueries({ queryKey: ["teams"] });
    },
    onError: () => toast.error("Failed to delete team."),
  });

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Team</h1>
        {isAdmin && (
          <button
            onClick={() => setShowCreate(!showCreate)}
            className="rounded-lg bg-primary-500 px-4 py-2 text-sm font-medium text-white hover:bg-primary-600"
          >
            + New Team
          </button>
        )}
      </div>

      {/* Create team form */}
      {showCreate && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!newTeamName.trim()) return;
            createMutation.mutate({
              name: newTeamName,
              description: newTeamDesc,
            });
          }}
          className="mb-6 rounded-xl border border-gray-200 bg-white p-4"
        >
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">
                Team Name *
              </label>
              <input
                type="text"
                value={newTeamName}
                onChange={(e) => setNewTeamName(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                autoFocus
                required
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">
                Description
              </label>
              <input
                type="text"
                value={newTeamDesc}
                onChange={(e) => setNewTeamDesc(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              />
            </div>
          </div>
          <div className="mt-3 flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setShowCreate(false)}
              className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={createMutation.isPending}
              className="rounded-lg bg-primary-500 px-4 py-1.5 text-sm font-medium text-white hover:bg-primary-600 disabled:opacity-50"
            >
              Create
            </button>
          </div>
        </form>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Agents */}
        <div className="rounded-xl border border-gray-200 bg-white">
          <div className="border-b border-gray-200 px-6 py-4">
            <h2 className="text-lg font-semibold text-gray-900">
              Agents ({agents?.length ?? 0})
            </h2>
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
                    {agent.first_name?.charAt(0) ?? "?"}
                    {agent.last_name?.charAt(0) ?? ""}
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
            <h2 className="text-lg font-semibold text-gray-900">
              Teams ({teams?.length ?? 0})
            </h2>
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
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-gray-500">
                        {team.members.length} members
                      </span>
                      {isAdmin && (
                        <button
                          onClick={() => {
                            if (window.confirm(`Delete team "${team.name}"?`)) {
                              deleteMutation.mutate(team.id);
                            }
                          }}
                          className="text-xs text-red-500 hover:text-red-700"
                        >
                          Delete
                        </button>
                      )}
                    </div>
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
                        {member.first_name?.charAt(0) ?? "?"}
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
