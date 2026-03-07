/**
 * Authentication hooks.
 */

import { useQuery } from "@tanstack/react-query";
import { fetchCurrentUser } from "@/api/users";
import { useAuthStore } from "@/store/authStore";

export function useCurrentUser() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  return useQuery({
    queryKey: ["currentUser"],
    queryFn: fetchCurrentUser,
    enabled: isAuthenticated,
    staleTime: 1000 * 60 * 5,
  });
}
