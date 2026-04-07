/**
 * Route guard that redirects unauthenticated users to login or setup.
 */

import { useState, useEffect } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuthStore } from "@/store/authStore";
import { fetchSetupStatus } from "@/api/setup";

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

  if (isAuthenticated) {
    return <>{children}</>;
  }

  if (checking) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50">
        <div className="text-sm text-gray-400">Loading...</div>
      </div>
    );
  }

  if (!initialized) {
    return <Navigate to="/setup" replace />;
  }

  return <Navigate to="/login" state={{ from: location }} replace />;
}
