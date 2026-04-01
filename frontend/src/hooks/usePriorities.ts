/**
 * React Query hooks for custom priority level operations.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createPriority,
  deletePriority,
  fetchPriorities,
  updatePriority,
} from "@/api/priorities";

export function usePriorities() {
  return useQuery({
    queryKey: ["priorities"],
    queryFn: fetchPriorities,
  });
}

export function useCreatePriority() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: {
      name: string;
      slug: string;
      color: string;
      position: number;
      is_default?: boolean;
    }) => createPriority(data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["priorities"] });
    },
  });
}

export function useUpdatePriority() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      id,
      ...data
    }: {
      id: string;
      name?: string;
      slug?: string;
      color?: string;
      position?: number;
      is_default?: boolean;
    }) => updatePriority(id, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["priorities"] });
    },
  });
}

export function useDeletePriority() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: deletePriority,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["priorities"] });
    },
  });
}
