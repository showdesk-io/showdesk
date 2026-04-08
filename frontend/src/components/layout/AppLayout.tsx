/**
 * Main application layout with sidebar navigation.
 *
 * Designed for agent productivity: dense information display,
 * keyboard-navigable, minimal clicks to reach any view.
 */

import { useState, useRef, useEffect } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { clsx } from "clsx";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuthStore } from "@/store/authStore";
import { useOrgStore } from "@/store/orgStore";
import { useCurrentUser } from "@/hooks/useAuth";
import { useWebSocket } from "@/hooks/useWebSocket";
import { fetchPlatformOrganizations } from "@/api/admin";

const navItems = [
  { to: "/", label: "Dashboard", icon: "grid" },
  { to: "/tickets", label: "Tickets", icon: "inbox" },
  { to: "/team", label: "Team", icon: "users" },
  { to: "/settings", label: "Settings", icon: "settings" },
] as const;

const adminNavItem = { to: "/admin", label: "Admin", icon: "shield" } as const;

function NavIcon({ icon }: { icon: string }) {
  const icons: Record<string, string> = {
    grid: "M4 4h6v6H4zm10 0h6v6h-6zm-10 10h6v6H4zm10 0h6v6h-6z",
    inbox: "M3 3h18v18H3zm2 8h14M8 11l-3 5h14l-3-5",
    users: "M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2M9 11a4 4 0 100-8 4 4 0 000 8zM23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75",
    settings: "M12 15a3 3 0 100-6 3 3 0 000 6z",
    shield: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z",
  };

  return (
    <svg
      className="h-5 w-5"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={1.5}
    >
      <path strokeLinecap="round" strokeLinejoin="round" d={icons[icon] ?? ""} />
    </svg>
  );
}

export function AppLayout() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const logout = useAuthStore((s) => s.logout);
  const clearActiveOrg = useOrgStore((s) => s.clearActiveOrg);
  const activeOrgId = useOrgStore((s) => s.activeOrgId);
  const { data: user } = useCurrentUser();

  // Maintain WebSocket connection for real-time updates
  useWebSocket();

  const isSuperuser = user?.is_superuser ?? false;
  const hasOrg = !!(user?.organization || activeOrgId);

  const handleLogout = () => {
    logout();
    clearActiveOrg();
    queryClient.clear();
    navigate("/login");
  };

  return (
    <div className="flex h-screen">
      {/* Sidebar */}
      <aside className="flex w-64 flex-col border-r border-gray-200 bg-white">
        {/* Logo */}
        <div className="flex h-16 items-center gap-2 border-b border-gray-200 px-6">
          <div className="h-8 w-8 rounded-lg bg-primary-500" />
          <span className="text-lg font-bold text-gray-900">Showdesk</span>
        </div>

        {/* Org switcher — superusers only */}
        {isSuperuser && <OrgSwitcher />}

        {/* Navigation */}
        <nav className="flex-1 space-y-1 px-3 py-4">
          {/* Standard nav items — only if user has an active org */}
          {hasOrg &&
            navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  clsx(
                    "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                    isActive
                      ? "bg-primary-50 text-primary-700"
                      : "text-gray-600 hover:bg-gray-50 hover:text-gray-900",
                  )
                }
              >
                <NavIcon icon={item.icon} />
                {item.label}
              </NavLink>
            ))}

          {/* Platform admin link — only visible to superusers */}
          {isSuperuser && (
            <>
              {hasOrg && <div className="my-2 border-t border-gray-200" />}
              <NavLink
                to={adminNavItem.to}
                className={({ isActive }) =>
                  clsx(
                    "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                    isActive
                      ? "bg-primary-50 text-primary-700"
                      : "text-gray-600 hover:bg-gray-50 hover:text-gray-900",
                  )
                }
              >
                <NavIcon icon={adminNavItem.icon} />
                {adminNavItem.label}
              </NavLink>
            </>
          )}
        </nav>

        {/* User section */}
        <div className="border-t border-gray-200 p-3">
          <div className="flex items-center gap-3 rounded-lg px-3 py-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary-100 text-xs font-semibold text-primary-700">
              {user?.first_name?.charAt(0) ?? "?"}
              {user?.last_name?.charAt(0) ?? ""}
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-gray-900">
                {user ? `${user.first_name} ${user.last_name}` : "Loading..."}
              </p>
              <p className="truncate text-xs text-gray-500">
                {user?.email ?? ""}
              </p>
            </div>
          </div>
          <button
            onClick={handleLogout}
            className="mt-1 flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-gray-500 transition-colors hover:bg-gray-50 hover:text-gray-900"
          >
            <svg
              className="h-5 w-5"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={1.5}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"
              />
            </svg>
            Sign out
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}

// ── Org Switcher ─────────────────────────────────────────────────────

function OrgSwitcher() {
  const queryClient = useQueryClient();
  const activeOrgId = useOrgStore((s) => s.activeOrgId);
  const activeOrgName = useOrgStore((s) => s.activeOrgName);
  const setActiveOrg = useOrgStore((s) => s.setActiveOrg);
  const clearActiveOrg = useOrgStore((s) => s.clearActiveOrg);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const { data } = useQuery({
    queryKey: ["platform-organizations-switcher"],
    queryFn: () => fetchPlatformOrganizations({ page_size: 100 }),
    staleTime: 1000 * 60 * 5,
  });

  const orgs = data?.results ?? [];

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const handleSelect = (orgId: string | null, orgName: string | null) => {
    if (orgId && orgName) {
      setActiveOrg(orgId, orgName);
    } else {
      clearActiveOrg();
    }
    setOpen(false);
    void queryClient.resetQueries();
  };

  return (
    <div ref={ref} className="relative border-b border-gray-200 px-3 py-2">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
      >
        <svg
          className="h-4 w-4 text-gray-400"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0H5m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"
          />
        </svg>
        <span className="flex-1 truncate text-left">
          {activeOrgName ?? "No organization"}
        </span>
        <svg
          className={clsx("h-4 w-4 text-gray-400 transition-transform", open && "rotate-180")}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="absolute left-3 right-3 top-full z-50 mt-1 max-h-64 overflow-auto rounded-lg border border-gray-200 bg-white shadow-lg">
          <button
            onClick={() => handleSelect(null, null)}
            className={clsx(
              "flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-gray-50",
              !activeOrgId ? "font-medium text-primary-700 bg-primary-50" : "text-gray-600",
            )}
          >
            No organization
          </button>
          <div className="border-t border-gray-100" />
          {orgs.map((org) => (
            <button
              key={org.id}
              onClick={() => handleSelect(org.id, org.name)}
              className={clsx(
                "flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-gray-50",
                activeOrgId === org.id ? "font-medium text-primary-700 bg-primary-50" : "text-gray-700",
              )}
            >
              <span className="truncate">{org.name}</span>
              {!org.is_active && (
                <span className="ml-2 rounded-full bg-red-100 px-1.5 py-0.5 text-xs text-red-700">
                  Suspended
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
