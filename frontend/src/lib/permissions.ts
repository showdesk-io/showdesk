import type { User } from "@/types";

/**
 * Whether a user administers the active organization, as the API's `is_org_admin`
 * decides it: a superuser's role means nothing, it defaults to end user.
 */
export function isOrgAdmin(
  user: Pick<User, "role" | "is_superuser"> | null | undefined,
): boolean {
  return !!user && (user.role === "admin" || !!user.is_superuser);
}
