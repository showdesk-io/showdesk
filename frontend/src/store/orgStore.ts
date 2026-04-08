/**
 * Organization impersonation state for platform admins.
 *
 * When a superuser selects an org via the org switcher,
 * the active org ID is sent as X-Showdesk-Org header on every API request.
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";

interface OrgState {
  activeOrgId: string | null;
  activeOrgName: string | null;
  setActiveOrg: (id: string, name: string) => void;
  clearActiveOrg: () => void;
}

export const useOrgStore = create<OrgState>()(
  persist(
    (set) => ({
      activeOrgId: null,
      activeOrgName: null,

      setActiveOrg: (id: string, name: string) =>
        set({ activeOrgId: id, activeOrgName: name }),

      clearActiveOrg: () =>
        set({ activeOrgId: null, activeOrgName: null }),
    }),
    {
      name: "showdesk-org",
      partialize: (state) => ({
        activeOrgId: state.activeOrgId,
        activeOrgName: state.activeOrgName,
      }),
    },
  ),
);
