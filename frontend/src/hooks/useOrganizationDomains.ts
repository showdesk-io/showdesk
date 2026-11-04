/**
 * React Query hooks for the organization's domains: their ownership and sending from them.
 *
 * A change to a domain can change the mailboxes too (which address replies go out from,
 * a public address freed by a verification), so every mutation refreshes both.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  checkSending,
  createOrganizationDomain,
  disableSending,
  enableSending,
  fetchOrganizationDomains,
  regenerateOrganizationDomainToken,
  verifyOrganizationDomain,
  type CreateDomainPayload,
} from "@/api/organizationDomains";
import type { OrganizationDomain } from "@/types";

/** Shared with DomainsList (Settings, General). */
export const ORGANIZATION_DOMAINS = ["organization-domains"] as const;
const MAILBOXES = ["mailboxes"] as const;

export function useOrganizationDomains() {
  return useQuery({ queryKey: ORGANIZATION_DOMAINS, queryFn: fetchOrganizationDomains });
}

/** `rowOf` picks the row a mutation answers, shown at once while both lists reload. */
function useDomainMutation<T, R>(
  mutationFn: (variables: T) => Promise<R>,
  rowOf: (result: R) => OrganizationDomain,
) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn,
    onSuccess: (result) => {
      const row = rowOf(result);
      queryClient.setQueryData<OrganizationDomain[]>(ORGANIZATION_DOMAINS, (rows) =>
        rows && rows.some((other) => other.id === row.id)
          ? rows.map((other) => (other.id === row.id ? row : other))
          : [...(rows ?? []), row],
      );
      void queryClient.invalidateQueries({ queryKey: ORGANIZATION_DOMAINS });
      void queryClient.invalidateQueries({ queryKey: MAILBOXES });
    },
  });
}

const itself = (row: OrganizationDomain) => row;

export function useCreateOrganizationDomain() {
  return useDomainMutation(
    (payload: CreateDomainPayload) => createOrganizationDomain(payload),
    itself,
  );
}

/** Runs the DNS check of a pending row; `verified` says whether it passed. */
export function useVerifyOrganizationDomain() {
  return useDomainMutation(
    (id: string) => verifyOrganizationDomain(id),
    (result) => result.domain,
  );
}

export function useRegenerateDomainToken() {
  return useDomainMutation((id: string) => regenerateOrganizationDomainToken(id), itself);
}

export function useEnableSending() {
  return useDomainMutation((id: string) => enableSending(id), itself);
}

export function useCheckSending() {
  return useDomainMutation((id: string) => checkSending(id), itself);
}

export function useDisableSending() {
  return useDomainMutation((id: string) => disableSending(id), itself);
}
