/**
 * React Query hooks for tag operations.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createTag, deleteTag, fetchTags, setTicketTags, updateTag } from "@/api/tags";

export function useTags() {
  return useQuery({
    queryKey: ["tags"],
    queryFn: fetchTags,
  });
}

export function useCreateTag() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: { name: string; color: string }) => createTag(data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["tags"] });
    },
  });
}

export function useUpdateTag() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      id,
      ...data
    }: {
      id: string;
      name?: string;
      color?: string;
    }) => updateTag(id, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["tags"] });
    },
  });
}

export function useDeleteTag() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: deleteTag,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["tags"] });
    },
  });
}

export function useSetTicketTags(ticketId?: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (args: string[] | { ticketId: string; tagIds: string[] }) => {
      if (Array.isArray(args)) {
        if (!ticketId) throw new Error("ticketId is required");
        return setTicketTags(ticketId, args);
      }
      return setTicketTags(args.ticketId, args.tagIds);
    },
    onSuccess: (_data, args) => {
      const id = Array.isArray(args) ? ticketId : args.ticketId;
      if (id) {
        void queryClient.invalidateQueries({ queryKey: ["ticket", id] });
      }
      void queryClient.invalidateQueries({ queryKey: ["tickets"] });
    },
  });
}
