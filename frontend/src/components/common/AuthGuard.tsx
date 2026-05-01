/**
 * Route guard that gates access to authenticated routes.
 *
 * Resolution order:
 *  - not authenticated         → /login (or /setup if instance not initialized)
 *  - authenticated, no org     → /signup (resume wizard)
 *  - authenticated, has org    → render children
 */

import { useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useAuthStore } from "@/store/authStore";
import { fetchSetupStatus } from "@/api/setup";
import { fetchCurrentUser } from "@/api/users";

interface AuthGuardProps {
  children: React.ReactNode;
}

export function AuthGuard({ children }: AuthGuardProps) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const location = useLocation();
  const [checking, setChecking] = useState(!isAuthenticated);
  const [initialized, setInitialized] = useState(true);

  useEffect(() => {
    if (isAuthenticated) return;
    fetchSetupStatus()
      .then((data) => setInitialized(data.initialized))
      .catch(() => setInitialized(true))
      .finally(() => setChecking(false));
  }, [isAuthenticated]);

  const { data: user, isLoading: userLoading } = useQuery({
    queryKey: ["currentUser"],
    queryFn: fetchCurrentUser,
    enabled: isAuthenticated,
    retry: false,
  });

  if (!isAuthenticated) {
    if (checking) {
      return (
        <div className="flex min-h-screen items-center justify-center bg-gray-50">
          <div className="text-sm text-gray-400">Loading...</div>
        </div>
      );
    }
    if (!initialized) return <Navigate to="/setup" replace />;
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (userLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50">
        <div className="text-sm text-gray-400">Loading...</div>
      </div>
    );
  }

  if (user && !user.organization) {
    return <Navigate to="/signup" replace />;
  }

  return <>{children}</>;
}
