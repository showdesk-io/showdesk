/**
 * Route guard that redirects non-superusers to the dashboard.
 */

import { Navigate } from "react-router-dom";
import { useCurrentUser } from "@/hooks/useAuth";

interface AdminGuardProps {
  children: React.ReactNode;
}

export function AdminGuard({ children }: AdminGuardProps) {
  const { data: user, isLoading } = useCurrentUser();

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50">
        <div className="text-sm text-gray-400">Loading...</div>
      </div>
    );
  }

  if (!user?.is_superuser) {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
}
