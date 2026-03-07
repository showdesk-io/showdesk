/**
 * Route guard that redirects unauthenticated users to the login page.
 */

import { Navigate, useLocation } from "react-router-dom";
import { useAuthStore } from "@/store/authStore";

interface AuthGuardProps {
  children: React.ReactNode;
}

export function AuthGuard({ children }: AuthGuardProps) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const location = useLocation();

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return <>{children}</>;
}
