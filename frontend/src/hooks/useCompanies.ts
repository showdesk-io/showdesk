/**
 * React Query hooks for company operations.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import {
  createCompany,
  deleteCompany,
  fetchCompanies,
  fetchCompany,
  fetchCompanyContacts,
  fetchCompanyTickets,
  updateCompany,
  type CompanyFilters,
  type CompanyWrite,
} from "@/api/companies";
import type { Company } from "@/types";

/** Contacts embed a summary of their company, and tickets one of their contact's. */
function invalidateWhatShowsCompanies(queryClient: QueryClient): void {
  for (const queryKey of [
    ["companies"],
    ["contacts"],
    ["contact"],
    ["tickets"],
    ["ticket"],
  ]) {
    void queryClient.invalidateQueries({ queryKey });
  }
}

export function useCompanies(params: CompanyFilters = {}) {
  return useQuery({
    queryKey: ["companies", params],
    queryFn: () => fetchCompanies(params),
  });
}

export function useCompany(id: string) {
  return useQuery({
    queryKey: ["company", id],
    queryFn: () => fetchCompany(id),
    enabled: !!id,
  });
}

export function useCompanyContacts(id: string) {
  return useQuery({
    queryKey: ["company", id, "contacts"],
    queryFn: () => fetchCompanyContacts(id),
    enabled: !!id,
  });
}

export function useCompanyTickets(id: string) {
  return useQuery({
    queryKey: ["company", id, "tickets"],
    queryFn: () => fetchCompanyTickets(id),
    enabled: !!id,
  });
}

export function useCreateCompany() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: CompanyWrite & Pick<Company, "name">) => createCompany(data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["companies"] });
    },
  });
}

export function useUpdateCompany() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, ...data }: { id: string } & CompanyWrite) =>
      updateCompany(id, data),
    onSuccess: (company, { id }) => {
      // At once: what the server made of it can differ, as a domain's normal form.
      queryClient.setQueryData(["company", id], company);
      void queryClient.invalidateQueries({ queryKey: ["company", id] });
      invalidateWhatShowsCompanies(queryClient);
    },
  });
}

export function useDeleteCompany() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: deleteCompany,
    onSuccess: (_data, id) => {
      // Removed, not invalidated: refetching it could only be a 404.
      queryClient.removeQueries({ queryKey: ["company", id] });
      invalidateWhatShowsCompanies(queryClient);
    },
  });
}
