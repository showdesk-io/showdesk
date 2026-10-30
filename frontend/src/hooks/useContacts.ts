/**
 * React Query hooks for contact operations.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import {
  anonymizeContact,
  createContact,
  createContactNote,
  deleteContact,
  exportContact,
  fetchContact,
  fetchContactNotes,
  fetchContacts,
  fetchContactTickets,
  updateContact,
  type ContactFilters,
  type ContactWrite,
} from "@/api/contacts";

/** Lists show contacts, companies count them, and tickets embed a summary of them. */
function invalidateWhatShowsContacts(queryClient: QueryClient): void {
  for (const queryKey of [
    ["contacts"],
    ["companies"],
    ["company"],
    ["tickets"],
    ["ticket"],
  ]) {
    void queryClient.invalidateQueries({ queryKey });
  }
}

export function useContacts(params: ContactFilters = {}) {
  return useQuery({
    queryKey: ["contacts", params],
    queryFn: () => fetchContacts(params),
  });
}

export function useContact(id: string) {
  return useQuery({
    queryKey: ["contact", id],
    queryFn: () => fetchContact(id),
    enabled: !!id,
  });
}

export function useContactTickets(id: string) {
  return useQuery({
    queryKey: ["contact", id, "tickets"],
    queryFn: () => fetchContactTickets(id),
    enabled: !!id,
  });
}

export function useContactNotes(id: string) {
  return useQuery({
    queryKey: ["contact", id, "notes"],
    queryFn: () => fetchContactNotes(id),
    enabled: !!id,
  });
}

export function useCreateContact() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: ContactWrite) => createContact(data),
    onSuccess: () => {
      // A new contact has no ticket yet, so no ticket can show it.
      void queryClient.invalidateQueries({ queryKey: ["contacts"] });
      void queryClient.invalidateQueries({ queryKey: ["companies"] });
      void queryClient.invalidateQueries({ queryKey: ["company"] });
    },
  });
}

export function useUpdateContact() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, ...data }: { id: string } & ContactWrite) =>
      updateContact(id, data),
    onSuccess: (_data, { id }) => {
      void queryClient.invalidateQueries({ queryKey: ["contact", id] });
      invalidateWhatShowsContacts(queryClient);
    },
  });
}

export function useDeleteContact() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: deleteContact,
    onSuccess: (_data, id) => {
      // Removed, not invalidated: refetching it could only be a 404.
      queryClient.removeQueries({ queryKey: ["contact", id] });
      invalidateWhatShowsContacts(queryClient);
    },
  });
}

export function useCreateContactNote(contactId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (body: string) => createContactNote(contactId, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["contact", contactId, "notes"],
      });
    },
  });
}

export function useExportContact() {
  return useMutation({ mutationFn: exportContact });
}

export function useAnonymizeContact() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: anonymizeContact,
    onSuccess: (_data, id) => {
      void queryClient.invalidateQueries({ queryKey: ["contact", id] });
      invalidateWhatShowsContacts(queryClient);
    },
  });
}
