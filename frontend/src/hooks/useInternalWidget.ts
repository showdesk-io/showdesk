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
  const accessToken = useAuthStore((s) => s.accessToken);

  // Key the query by the access token so a logout/login as a different
  // user refetches the identity instead of serving the previous user's
  // cached response.
  const { data: identity } = useQuery({
    queryKey: ["internal-widget-identity", accessToken],
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
      // reset() (not destroy()) so the previous user's session_id is
      // dropped from localStorage when the widget remounts for someone else.
      // Fall back to destroy() for cached older widget builds without reset().
      try {
        const w = window.Showdesk;
        if (typeof w?.reset === "function") {
          w.reset();
        } else if (typeof w?.destroy === "function") {
          w.destroy();
        }
      } catch {
        /* ignore */
      }
    };
  }, [identity]);
}
