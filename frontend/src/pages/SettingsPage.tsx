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
import { useTags, useCreateTag, useUpdateTag, useDeleteTag } from "@/hooks/useTags";
import {
  usePriorities,
  useCreatePriority,
  useUpdatePriority,
  useDeletePriority,
} from "@/hooks/usePriorities";
import type { PriorityLevel } from "@/api/priorities";
import type { Organization, Tag, User, UserRole } from "@/types";

const tabs = ["Agents", "Tags", "Priorities", "Widget", "Organization"] as const;
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
        {activeTab === "Tags" && <TagsTab isAdmin={isAdmin} />}
        {activeTab === "Priorities" && <PrioritiesTab isAdmin={isAdmin} />}
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

// ── Tags Tab ──────────────────────────────────────────────────────────

const TAG_COLORS = [
  "#6B7280", "#EF4444", "#F59E0B", "#10B981", "#3B82F6",
  "#8B5CF6", "#EC4899", "#14B8A6", "#F97316", "#06B6D4",
];

function TagsTab({ isAdmin }: { isAdmin: boolean }) {
  const { data: tags, isLoading } = useTags();
  const createTag = useCreateTag();
  const updateTag = useUpdateTag();
  const deleteTag = useDeleteTag();

  const [showForm, setShowForm] = useState(false);
  const [editingTag, setEditingTag] = useState<Tag | null>(null);
  const [name, setName] = useState("");
  const [color, setColor] = useState(TAG_COLORS[0]);

  const resetForm = () => {
    setShowForm(false);
    setEditingTag(null);
    setName("");
    setColor(TAG_COLORS[0]);
  };

  const handleEdit = (tag: Tag) => {
    setEditingTag(tag);
    setName(tag.name);
    setColor(tag.color);
    setShowForm(true);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;

    if (editingTag) {
      updateTag.mutate(
        { id: editingTag.id, name, color },
        {
          onSuccess: () => {
            toast.success("Tag updated.");
            resetForm();
          },
          onError: () => toast.error("Failed to update tag."),
        },
      );
    } else {
      createTag.mutate(
        { name, color },
        {
          onSuccess: () => {
            toast.success("Tag created.");
            resetForm();
          },
          onError: () => toast.error("Failed to create tag."),
        },
      );
    }
  };

  const handleDelete = (tag: Tag) => {
    deleteTag.mutate(tag.id, {
      onSuccess: () => toast.success(`Tag "${tag.name}" deleted.`),
      onError: () => toast.error("Failed to delete tag."),
    });
  };

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
          Tags ({tags?.length ?? 0})
        </h2>
        {isAdmin && (
          <button
            onClick={() => {
              resetForm();
              setShowForm(true);
            }}
            className="rounded-lg bg-primary-500 px-4 py-2 text-sm font-medium text-white hover:bg-primary-600"
          >
            + New Tag
          </button>
        )}
      </div>

      {/* Create / Edit form */}
      {showForm && (
        <form
          onSubmit={handleSubmit}
          className="mb-6 rounded-xl border border-gray-200 bg-white p-4"
        >
          <div className="flex items-end gap-4">
            <div className="flex-1">
              <label className="mb-1 block text-xs font-medium text-gray-600">
                Name *
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none"
                placeholder="e.g. Bug, Feature, Billing..."
                required
                autoFocus
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">
                Color
              </label>
              <div className="flex gap-1">
                {TAG_COLORS.map((c) => (
                  <button
                    key={c}
                    type="button"
                    onClick={() => setColor(c)}
                    className={clsx(
                      "h-8 w-8 rounded-full border-2 transition-transform",
                      color === c
                        ? "scale-110 border-gray-900"
                        : "border-transparent hover:scale-105",
                    )}
                    style={{ backgroundColor: c }}
                  />
                ))}
              </div>
            </div>
          </div>
          <div className="mt-4 flex justify-end gap-2">
            <button
              type="button"
              onClick={resetForm}
              className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={createTag.isPending || updateTag.isPending || !name.trim()}
              className="rounded-lg bg-primary-500 px-4 py-1.5 text-sm font-medium text-white hover:bg-primary-600 disabled:opacity-50"
            >
              {editingTag ? "Update" : "Create"}
            </button>
          </div>
        </form>
      )}

      {/* Tag list */}
      {tags?.length === 0 ? (
        <div className="rounded-xl border border-gray-200 bg-white px-6 py-12 text-center text-gray-500">
          No tags yet. Create your first tag to categorize tickets.
        </div>
      ) : (
        <div className="rounded-xl border border-gray-200 bg-white">
          <div className="divide-y divide-gray-100">
            {tags?.map((tag) => (
              <div
                key={tag.id}
                className="flex items-center gap-4 px-6 py-3"
              >
                <span
                  className="h-4 w-4 rounded-full"
                  style={{ backgroundColor: tag.color }}
                />
                <span className="flex-1 text-sm font-medium text-gray-900">
                  {tag.name}
                </span>
                <span className="font-mono text-xs text-gray-400">
                  {tag.color}
                </span>
                {isAdmin && (
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleEdit(tag)}
                      className="rounded px-2 py-1 text-xs text-gray-500 hover:bg-gray-100 hover:text-gray-700"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => handleDelete(tag)}
                      disabled={deleteTag.isPending}
                      className="rounded px-2 py-1 text-xs text-red-500 hover:bg-red-50 hover:text-red-700"
                    >
                      Delete
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Priorities Tab ────────────────────────────────────────────────────

const PRIORITY_COLORS = [
  "#6B7280", "#EF4444", "#F59E0B", "#F97316", "#10B981",
  "#3B82F6", "#8B5CF6", "#EC4899", "#14B8A6", "#06B6D4",
];

function PrioritiesTab({ isAdmin }: { isAdmin: boolean }) {
  const { data: priorities, isLoading } = usePriorities();
  const createPriority = useCreatePriority();
  const updatePriority = useUpdatePriority();
  const deletePriority = useDeletePriority();

  const [showForm, setShowForm] = useState(false);
  const [editingPriority, setEditingPriority] = useState<PriorityLevel | null>(null);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [color, setColor] = useState(PRIORITY_COLORS[0]);
  const [position, setPosition] = useState(0);
  const [isDefault, setIsDefault] = useState(false);

  const resetForm = () => {
    setShowForm(false);
    setEditingPriority(null);
    setName("");
    setSlug("");
    setColor(PRIORITY_COLORS[0]);
    setPosition(priorities?.length ?? 0);
    setIsDefault(false);
  };

  const handleEdit = (p: PriorityLevel) => {
    setEditingPriority(p);
    setName(p.name);
    setSlug(p.slug);
    setColor(p.color);
    setPosition(p.position);
    setIsDefault(p.is_default);
    setShowForm(true);
  };

  // Auto-generate slug from name
  const handleNameChange = (value: string) => {
    setName(value);
    if (!editingPriority) {
      setSlug(
        value
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, "_")
          .replace(/^_|_$/g, ""),
      );
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !slug.trim()) return;

    if (editingPriority) {
      updatePriority.mutate(
        { id: editingPriority.id, name, slug, color, position, is_default: isDefault },
        {
          onSuccess: () => {
            toast.success("Priority updated.");
            resetForm();
          },
          onError: () => toast.error("Failed to update priority."),
        },
      );
    } else {
      createPriority.mutate(
        { name, slug, color, position, is_default: isDefault },
        {
          onSuccess: () => {
            toast.success("Priority created.");
            resetForm();
          },
          onError: () => toast.error("Failed to create priority."),
        },
      );
    }
  };

  const handleDelete = (p: PriorityLevel) => {
    deletePriority.mutate(p.id, {
      onSuccess: () => toast.success(`Priority "${p.name}" deleted.`),
      onError: () => toast.error("Failed to delete priority."),
    });
  };

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
        <div>
          <h2 className="text-lg font-semibold text-gray-900">
            Priorities ({priorities?.length ?? 0})
          </h2>
          <p className="text-sm text-gray-500">
            Define custom priority levels with colors for your tickets.
          </p>
        </div>
        {isAdmin && (
          <button
            onClick={() => {
              resetForm();
              setPosition(priorities?.length ?? 0);
              setShowForm(true);
            }}
            className="rounded-lg bg-primary-500 px-4 py-2 text-sm font-medium text-white hover:bg-primary-600"
          >
            + New Priority
          </button>
        )}
      </div>

      {/* Create / Edit form */}
      {showForm && (
        <form
          onSubmit={handleSubmit}
          className="mb-6 rounded-xl border border-gray-200 bg-white p-4"
        >
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">
                Name *
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => handleNameChange(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none"
                placeholder="e.g. Critical, Blocker..."
                required
                autoFocus
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">
                Slug *
              </label>
              <input
                type="text"
                value={slug}
                onChange={(e) => setSlug(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono focus:border-primary-500 focus:outline-none"
                placeholder="e.g. critical"
                required
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">
                Position (order)
              </label>
              <input
                type="number"
                value={position}
                onChange={(e) => setPosition(parseInt(e.target.value, 10) || 0)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none"
                min={0}
              />
            </div>
            <div className="flex items-end gap-4">
              <label className="flex items-center gap-2 pb-2 text-sm">
                <input
                  type="checkbox"
                  checked={isDefault}
                  onChange={(e) => setIsDefault(e.target.checked)}
                  className="rounded border-gray-300 text-primary-500 focus:ring-primary-500"
                />
                Default priority
              </label>
            </div>
          </div>

          <div className="mt-3">
            <label className="mb-1 block text-xs font-medium text-gray-600">
              Color
            </label>
            <div className="flex items-center gap-2">
              <div className="flex gap-1">
                {PRIORITY_COLORS.map((c) => (
                  <button
                    key={c}
                    type="button"
                    onClick={() => setColor(c)}
                    className={clsx(
                      "h-8 w-8 rounded-full border-2 transition-transform",
                      color === c
                        ? "scale-110 border-gray-900"
                        : "border-transparent hover:scale-105",
                    )}
                    style={{ backgroundColor: c }}
                  />
                ))}
              </div>
              <input
                type="color"
                value={color}
                onChange={(e) => setColor(e.target.value)}
                className="ml-2 h-8 w-8 cursor-pointer rounded border border-gray-300"
              />
              <span className="ml-1 font-mono text-xs text-gray-400">{color}</span>
            </div>
          </div>

          <div className="mt-4 flex justify-end gap-2">
            <button
              type="button"
              onClick={resetForm}
              className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={createPriority.isPending || updatePriority.isPending || !name.trim() || !slug.trim()}
              className="rounded-lg bg-primary-500 px-4 py-1.5 text-sm font-medium text-white hover:bg-primary-600 disabled:opacity-50"
            >
              {editingPriority ? "Update" : "Create"}
            </button>
          </div>
        </form>
      )}

      {/* Priority list */}
      {priorities?.length === 0 ? (
        <div className="rounded-xl border border-gray-200 bg-white px-6 py-12 text-center text-gray-500">
          No priorities defined. Create your first priority level.
        </div>
      ) : (
        <div className="rounded-xl border border-gray-200 bg-white">
          <div className="divide-y divide-gray-100">
            {priorities?.map((p) => (
              <div
                key={p.id}
                className="flex items-center gap-4 px-6 py-3"
              >
                <span className="text-xs text-gray-400 w-6 text-right">
                  {p.position}
                </span>
                <span
                  className="h-4 w-4 rounded-full flex-shrink-0"
                  style={{ backgroundColor: p.color }}
                />
                <span className="flex-1 text-sm font-medium text-gray-900">
                  {p.name}
                </span>
                <span className="font-mono text-xs text-gray-400">
                  {p.slug}
                </span>
                {p.is_default && (
                  <span className="rounded-full bg-primary-100 px-2 py-0.5 text-[10px] font-medium text-primary-700">
                    default
                  </span>
                )}
                <span className="font-mono text-xs text-gray-400">
                  {p.color}
                </span>
                {isAdmin && (
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleEdit(p)}
                      className="rounded px-2 py-1 text-xs text-gray-500 hover:bg-gray-100 hover:text-gray-700"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => handleDelete(p)}
                      disabled={deletePriority.isPending}
                      className="rounded px-2 py-1 text-xs text-red-500 hover:bg-red-50 hover:text-red-700"
                    >
                      Delete
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
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
