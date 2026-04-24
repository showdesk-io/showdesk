/**
 * Mount the in-app Showdesk widget (dogfooding).
 *
 * Fetches the internal org token + HMAC identity for the authenticated
 * user, then initializes the widget loaded from /cdn/widget.js.
 */

import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAuthStore } from "@/store/authStore";
import { fetchInternalWidgetIdentity } from "@/api/widget";

export function useInternalWidget(): void {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  const { data: identity } = useQuery({
    queryKey: ["internal-widget-identity"],
    queryFn: fetchInternalWidgetIdentity,
    enabled: isAuthenticated,
    staleTime: Infinity,
    retry: 1,
  });

  useEffect(() => {
    if (!identity) return;

    let cancelled = false;
    let pollTimer: number | undefined;

    const tryInit = () => {
      if (cancelled) return;
      if (!window.Showdesk) {
        pollTimer = window.setTimeout(tryInit, 50);
        return;
      }
      window.Showdesk.init({
        token: identity.token,
        navigationMode: "spa",
        user: {
          id: identity.external_user_id,
          name: identity.user.name,
          email: identity.user.email,
          hash: identity.user_hash,
        },
      });
    };

    tryInit();

    return () => {
      cancelled = true;
      if (pollTimer) window.clearTimeout(pollTimer);
      window.Showdesk?.destroy();
    };
  }, [identity]);
}
