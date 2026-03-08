/**
 * React Query hooks for ticket operations.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  assignTicket,
  closeTicket,
  createMessage,
  createTicket,
  fetchTicket,
  fetchTickets,
  reopenTicket,
  resolveTicket,
  updateTicket,
  type CreateTicketData,
  type TicketFilters,
} from "@/api/tickets";

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
  });
}

export function useCreateTicket() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: CreateTicketData) => createTicket(data),
    onSuccess: () => {
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
      priority?: string;
      assigned_agent?: string | null;
    }) => updateTicket(ticketId, data),
    onSuccess: (_data, variables) => {
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
      void queryClient.invalidateQueries({ queryKey: ["ticket", ticket.id] });
      void queryClient.invalidateQueries({ queryKey: ["tickets"] });
      void queryClient.invalidateQueries({ queryKey: ["ticketStats"] });
    },
  });
}
