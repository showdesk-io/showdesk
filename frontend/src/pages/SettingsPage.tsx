/**
 * Settings page with tabs: Agents, Widget, Organization.
 */

import { useState } from "react";
import { clsx } from "clsx";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import {
  fetchAgents,
  fetchOrganization,
  inviteAgent,
  regenerateApiToken,
  toggleUserActive,
  updateOrganization,
  updateUser,
} from "@/api/users";
import { useCurrentUser } from "@/hooks/useAuth";
import type { Organization, User, UserRole } from "@/types";

const tabs = ["Agents", "Widget", "Organization"] as const;
type Tab = (typeof tabs)[number];

export function SettingsPage() {
  const [activeTab, setActiveTab] = useState<Tab>("Agents");
  const { data: currentUser } = useCurrentUser();
  const isAdmin =
    currentUser?.role === "admin" || false;

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-gray-200 bg-white px-6 pt-6">
        <h1 className="mb-4 text-2xl font-bold text-gray-900">Settings</h1>
        <div className="flex gap-1">
          {tabs.map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={clsx(
                "rounded-t-lg px-4 py-2 text-sm font-medium transition-colors",
                activeTab === tab
                  ? "border-b-2 border-primary-500 text-primary-700"
                  : "text-gray-500 hover:text-gray-700",
              )}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-auto p-6">
        {activeTab === "Agents" && <AgentsTab isAdmin={isAdmin} />}
        {activeTab === "Widget" && <WidgetTab isAdmin={isAdmin} />}
        {activeTab === "Organization" && (
          <OrganizationTab isAdmin={isAdmin} />
        )}
      </div>
    </div>
  );
}

// ── Agents Tab ────────────────────────────────────────────────────────

function AgentsTab({ isAdmin }: { isAdmin: boolean }) {
  const queryClient = useQueryClient();
  const { data: agents, isLoading } = useQuery({
    queryKey: ["agents"],
    queryFn: fetchAgents,
  });

  const [showInvite, setShowInvite] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteFirstName, setInviteFirstName] = useState("");
  const [inviteLastName, setInviteLastName] = useState("");
  const [inviteRole, setInviteRole] = useState<"agent" | "admin">("agent");

  const inviteMutation = useMutation({
    mutationFn: inviteAgent,
    onSuccess: () => {
      toast.success("Agent invited! They will receive an email.");
      setShowInvite(false);
      setInviteEmail("");
      setInviteFirstName("");
      setInviteLastName("");
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
    },
    onError: () => toast.error("Failed to invite agent."),
  });

  const toggleMutation = useMutation({
    mutationFn: toggleUserActive,
    onSuccess: (user: User) => {
      toast.success(
        `${user.first_name || user.email} ${user.is_active ? "activated" : "deactivated"}.`,
      );
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
    },
    onError: () => toast.error("Failed to update user."),
  });

  const roleMutation = useMutation({
    mutationFn: ({ id, role }: { id: string; role: UserRole }) =>
      updateUser(id, { role }),
    onSuccess: () => {
      toast.success("Role updated.");
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
    },
    onError: () => toast.error("Failed to update role."),
  });

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary-500 border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900">
          Agents ({agents?.length ?? 0})
        </h2>
        {isAdmin && (
          <button
            onClick={() => setShowInvite(!showInvite)}
            className="rounded-lg bg-primary-500 px-4 py-2 text-sm font-medium text-white hover:bg-primary-600"
          >
            + Invite Agent
          </button>
        )}
      </div>

      {/* Invite form */}
      {showInvite && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            inviteMutation.mutate({
              email: inviteEmail,
              first_name: inviteFirstName,
              last_name: inviteLastName,
              role: inviteRole,
            });
          }}
          className="mb-6 rounded-xl border border-gray-200 bg-white p-4"
        >
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">
                Email *
              </label>
              <input
                type="email"
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none"
                required
                autoFocus
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">
                Role
              </label>
              <select
                value={inviteRole}
                onChange={(e) =>
                  setInviteRole(e.target.value as "agent" | "admin")
                }
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              >
                <option value="agent">Agent</option>
                <option value="admin">Admin</option>
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">
                First Name
              </label>
              <input
                type="text"
                value={inviteFirstName}
                onChange={(e) => setInviteFirstName(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">
                Last Name
              </label>
              <input
                type="text"
                value={inviteLastName}
                onChange={(e) => setInviteLastName(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              />
            </div>
          </div>
          <div className="mt-4 flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setShowInvite(false)}
              className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={inviteMutation.isPending || !inviteEmail}
              className="rounded-lg bg-primary-500 px-4 py-1.5 text-sm font-medium text-white hover:bg-primary-600 disabled:opacity-50"
            >
              {inviteMutation.isPending ? "Inviting..." : "Send Invite"}
            </button>
          </div>
        </form>
      )}

      {/* Agent list */}
      <div className="rounded-xl border border-gray-200 bg-white">
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
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-gray-900">
                  {agent.first_name} {agent.last_name}
                </p>
                <p className="text-xs text-gray-500">{agent.email}</p>
              </div>

              {isAdmin ? (
                <select
                  value={agent.role}
                  onChange={(e) =>
                    roleMutation.mutate({
                      id: agent.id,
                      role: e.target.value as UserRole,
                    })
                  }
                  className="rounded-lg border border-gray-300 px-2 py-1 text-xs"
                >
                  <option value="agent">Agent</option>
                  <option value="admin">Admin</option>
                </select>
              ) : (
                <span
                  className={clsx(
                    "rounded-full px-2 py-0.5 text-xs font-medium",
                    agent.role === "admin"
                      ? "bg-purple-100 text-purple-700"
                      : "bg-blue-100 text-blue-700",
                  )}
                >
                  {agent.role}
                </span>
              )}

              <span
                className={clsx(
                  "h-2.5 w-2.5 rounded-full",
                  agent.is_available ? "bg-green-400" : "bg-gray-300",
                )}
                title={agent.is_available ? "Available" : "Unavailable"}
              />

              {isAdmin && (
                <button
                  onClick={() => toggleMutation.mutate(agent.id)}
                  disabled={toggleMutation.isPending}
                  className={clsx(
                    "rounded-lg px-3 py-1 text-xs font-medium",
                    agent.is_active
                      ? "border border-red-200 text-red-600 hover:bg-red-50"
                      : "border border-green-200 text-green-600 hover:bg-green-50",
                  )}
                >
                  {agent.is_active ? "Deactivate" : "Activate"}
                </button>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Widget Tab ────────────────────────────────────────────────────────

function WidgetTab({ isAdmin }: { isAdmin: boolean }) {
  const queryClient = useQueryClient();
  const { data: org, isLoading } = useQuery({
    queryKey: ["organization"],
    queryFn: fetchOrganization,
  });

  const [widgetColor, setWidgetColor] = useState("");
  const [widgetPosition, setWidgetPosition] = useState("");
  const [widgetGreeting, setWidgetGreeting] = useState("");
  const [initialized, setInitialized] = useState(false);

  // Initialize form state when org loads
  if (org && !initialized) {
    setWidgetColor(org.widget_color);
    setWidgetPosition(org.widget_position);
    setWidgetGreeting(org.widget_greeting);
    setInitialized(true);
  }

  const updateMutation = useMutation({
    mutationFn: (data: Partial<Organization>) =>
      updateOrganization(org!.id, data),
    onSuccess: () => {
      toast.success("Widget settings saved.");
      void queryClient.invalidateQueries({ queryKey: ["organization"] });
    },
    onError: () => toast.error("Failed to save settings."),
  });

  const regenMutation = useMutation({
    mutationFn: () => regenerateApiToken(org!.id),
    onSuccess: () => {
      toast.success("API token regenerated.");
      void queryClient.invalidateQueries({ queryKey: ["organization"] });
    },
    onError: () => toast.error("Failed to regenerate token."),
  });

  if (isLoading || !org) {
    return (
      <div className="flex justify-center py-12">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary-500 border-t-transparent" />
      </div>
    );
  }

  const snippet = `<script src="https://cdn.showdesk.io/widget.js" data-token="${org.api_token}"></script>`;

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      {/* Widget Configuration */}
      <div className="rounded-xl border border-gray-200 bg-white p-6">
        <h2 className="mb-4 text-lg font-semibold text-gray-900">
          Widget Appearance
        </h2>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              Primary Color
            </label>
            <div className="flex items-center gap-2">
              <input
                type="color"
                value={widgetColor}
                onChange={(e) => setWidgetColor(e.target.value)}
                className="h-10 w-10 cursor-pointer rounded border border-gray-300"
                disabled={!isAdmin}
              />
              <input
                type="text"
                value={widgetColor}
                onChange={(e) => setWidgetColor(e.target.value)}
                className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono"
                disabled={!isAdmin}
              />
            </div>
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              Position
            </label>
            <select
              value={widgetPosition}
              onChange={(e) => setWidgetPosition(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              disabled={!isAdmin}
            >
              <option value="bottom-right">Bottom Right</option>
              <option value="bottom-left">Bottom Left</option>
            </select>
          </div>

          <div className="col-span-2">
            <label className="mb-1 block text-sm font-medium text-gray-700">
              Greeting Message
            </label>
            <input
              type="text"
              value={widgetGreeting}
              onChange={(e) => setWidgetGreeting(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              disabled={!isAdmin}
            />
          </div>
        </div>

        {isAdmin && (
          <button
            onClick={() =>
              updateMutation.mutate({
                widget_color: widgetColor,
                widget_position: widgetPosition as
                  | "bottom-right"
                  | "bottom-left",
                widget_greeting: widgetGreeting,
              })
            }
            disabled={updateMutation.isPending}
            className="mt-4 rounded-lg bg-primary-500 px-4 py-2 text-sm font-medium text-white hover:bg-primary-600 disabled:opacity-50"
          >
            {updateMutation.isPending ? "Saving..." : "Save Changes"}
          </button>
        )}
      </div>

      {/* Embed Snippet */}
      <div className="rounded-xl border border-gray-200 bg-white p-6">
        <h2 className="mb-2 text-lg font-semibold text-gray-900">
          Embed Snippet
        </h2>
        <p className="mb-3 text-sm text-gray-500">
          Add this script tag to your website to enable the Showdesk widget.
        </p>
        <div className="relative">
          <pre className="overflow-x-auto rounded-lg bg-gray-900 p-4 text-sm text-green-400">
            {snippet}
          </pre>
          <button
            onClick={() => {
              void navigator.clipboard.writeText(snippet);
              toast.success("Copied to clipboard!");
            }}
            className="absolute right-2 top-2 rounded bg-gray-700 px-2 py-1 text-xs text-gray-300 hover:bg-gray-600"
          >
            Copy
          </button>
        </div>
      </div>

      {/* API Token */}
      <div className="rounded-xl border border-gray-200 bg-white p-6">
        <h2 className="mb-2 text-lg font-semibold text-gray-900">API Token</h2>
        <p className="mb-3 text-sm text-gray-500">
          Used by the widget and API to authenticate requests.
        </p>
        <div className="flex items-center gap-3">
          <code className="flex-1 rounded-lg bg-gray-100 px-4 py-2 text-sm font-mono text-gray-700">
            {org.api_token}
          </code>
          {isAdmin && (
            <button
              onClick={() => {
                if (window.confirm("Regenerate token? The old one will stop working.")) {
                  regenMutation.mutate();
                }
              }}
              disabled={regenMutation.isPending}
              className="rounded-lg border border-red-200 px-3 py-2 text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
            >
              Regenerate
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Organization Tab ──────────────────────────────────────────────────

function OrganizationTab({ isAdmin }: { isAdmin: boolean }) {
  const queryClient = useQueryClient();
  const { data: org, isLoading } = useQuery({
    queryKey: ["organization"],
    queryFn: fetchOrganization,
  });

  const [name, setName] = useState("");
  const [domain, setDomain] = useState("");
  const [initialized, setInitialized] = useState(false);

  if (org && !initialized) {
    setName(org.name);
    setDomain(org.domain);
    setInitialized(true);
  }

  const updateMutation = useMutation({
    mutationFn: (data: Partial<Organization>) =>
      updateOrganization(org!.id, data),
    onSuccess: () => {
      toast.success("Organization updated.");
      void queryClient.invalidateQueries({ queryKey: ["organization"] });
    },
    onError: () => toast.error("Failed to update organization."),
  });

  if (isLoading || !org) {
    return (
      <div className="flex justify-center py-12">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary-500 border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl">
      <div className="rounded-xl border border-gray-200 bg-white p-6">
        <h2 className="mb-4 text-lg font-semibold text-gray-900">
          Organization Details
        </h2>

        <div className="space-y-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              disabled={!isAdmin}
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              Slug
            </label>
            <input
              type="text"
              value={org.slug}
              className="w-full rounded-lg border border-gray-300 bg-gray-50 px-3 py-2 text-sm text-gray-500"
              disabled
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              Domain
            </label>
            <input
              type="text"
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              placeholder="example.com"
              disabled={!isAdmin}
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">
                Video Expiration (days)
              </label>
              <input
                type="number"
                value={org.video_expiration_days}
                className="w-full rounded-lg border border-gray-300 bg-gray-50 px-3 py-2 text-sm text-gray-500"
                disabled
              />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">
                Max Recording (seconds)
              </label>
              <input
                type="number"
                value={org.video_max_duration_seconds}
                className="w-full rounded-lg border border-gray-300 bg-gray-50 px-3 py-2 text-sm text-gray-500"
                disabled
              />
            </div>
          </div>
        </div>

        {isAdmin && (
          <button
            onClick={() => updateMutation.mutate({ name, domain })}
            disabled={updateMutation.isPending}
            className="mt-6 rounded-lg bg-primary-500 px-4 py-2 text-sm font-medium text-white hover:bg-primary-600 disabled:opacity-50"
          >
            {updateMutation.isPending ? "Saving..." : "Save Changes"}
          </button>
        )}
      </div>
    </div>
  );
}
