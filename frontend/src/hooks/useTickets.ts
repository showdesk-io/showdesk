/**
 * React Query hooks for ticket operations.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import {
  assignTicket,
  bulkUpdateTickets,
  closeTicket,
  createMessage,
  createTicket,
  deleteMessage,
  fetchTicket,
  fetchTickets,
  reopenTicket,
  resolveTicket,
  updateTicket,
  type CreateTicketData,
  type TicketFilters,
} from "@/api/tickets";

/** A ticket also shows on its contact's and its company's timeline, with its status. */
function invalidateTimelines(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: ["contact"] });
  void queryClient.invalidateQueries({ queryKey: ["company"] });
}

export function useTickets(filters: TicketFilters = {}) {
  return useQuery({
    queryKey: ["tickets", filters],
    queryFn: () => fetchTickets(filters),
  });
}

export function useTicket(id: string) {
  return useQuery({
    queryKey: ["ticket", id],
    queryFn: () => fetchTicket(id),
    enabled: !!id,
    refetchInterval: 10_000,
  });
}

export function useCreateTicket() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: CreateTicketData) => createTicket(data),
    onSuccess: () => {
      invalidateTimelines(queryClient);
      void queryClient.invalidateQueries({ queryKey: ["tickets"] });
      void queryClient.invalidateQueries({ queryKey: ["ticketStats"] });
    },
  });
}

export function useUpdateTicket() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      ticketId,
      ...data
    }: {
      ticketId: string;
      [key: string]: unknown;
    }) => updateTicket(ticketId, data as Record<string, unknown>),
    onSuccess: (_data, variables) => {
      invalidateTimelines(queryClient);
      void queryClient.invalidateQueries({
        queryKey: ["ticket", variables.ticketId],
      });
      void queryClient.invalidateQueries({ queryKey: ["tickets"] });
      void queryClient.invalidateQueries({ queryKey: ["ticketStats"] });
    },
  });
}

export function useCreateMessage(ticketId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: { body: string; message_type: string }) =>
      createMessage(ticketId, data),
    onSuccess: () => {
      invalidateTimelines(queryClient);
      void queryClient.invalidateQueries({ queryKey: ["ticket", ticketId] });
    },
  });
}

export function useAssignTicket() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      ticketId,
      ...data
    }: {
      ticketId: string;
      agent_id?: string;
      team_id?: string;
    }) => assignTicket(ticketId, data),
    onSuccess: (ticket) => {
      invalidateTimelines(queryClient);
      void queryClient.invalidateQueries({ queryKey: ["ticket", ticket.id] });
      void queryClient.invalidateQueries({ queryKey: ["tickets"] });
    },
  });
}

export function useResolveTicket() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: resolveTicket,
    onSuccess: (ticket) => {
      invalidateTimelines(queryClient);
      void queryClient.invalidateQueries({ queryKey: ["ticket", ticket.id] });
      void queryClient.invalidateQueries({ queryKey: ["tickets"] });
      void queryClient.invalidateQueries({ queryKey: ["ticketStats"] });
    },
  });
}

export function useCloseTicket() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: closeTicket,
    onSuccess: (ticket) => {
      invalidateTimelines(queryClient);
      void queryClient.invalidateQueries({ queryKey: ["ticket", ticket.id] });
      void queryClient.invalidateQueries({ queryKey: ["tickets"] });
      void queryClient.invalidateQueries({ queryKey: ["ticketStats"] });
    },
  });
}

export function useReopenTicket() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: reopenTicket,
    onSuccess: (ticket) => {
      invalidateTimelines(queryClient);
      void queryClient.invalidateQueries({ queryKey: ["ticket", ticket.id] });
      void queryClient.invalidateQueries({ queryKey: ["tickets"] });
      void queryClient.invalidateQueries({ queryKey: ["ticketStats"] });
    },
  });
}

export function useBulkUpdateTickets() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: bulkUpdateTickets,
    onSuccess: () => {
      invalidateTimelines(queryClient);
      void queryClient.invalidateQueries({ queryKey: ["tickets"] });
      void queryClient.invalidateQueries({ queryKey: ["ticketStats"] });
    },
  });
}

export function useDeleteMessage(ticketId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: deleteMessage,
    onSuccess: () => {
      invalidateTimelines(queryClient);
      void queryClient.invalidateQueries({ queryKey: ["ticket", ticketId] });
      void queryClient.invalidateQueries({ queryKey: ["tickets"] });
    },
  });
}
