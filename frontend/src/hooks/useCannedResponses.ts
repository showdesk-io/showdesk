/**
 * React Query hooks for canned response operations.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createCannedResponse,
  deleteCannedResponse,
  fetchCannedResponses,
  recordCannedResponseUse,
  updateCannedResponse,
} from "@/api/cannedResponses";

export function useCannedResponses() {
  return useQuery({
    queryKey: ["canned-responses"],
    queryFn: fetchCannedResponses,
  });
}

export function useCreateCannedResponse() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      name: string;
      shortcut?: string;
      body: string;
      is_shared?: boolean;
      position?: number;
    }) => createCannedResponse(data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["canned-responses"] });
    },
  });
}

export function useUpdateCannedResponse() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      ...data
    }: {
      id: string;
      name?: string;
      shortcut?: string;
      body?: string;
      is_shared?: boolean;
      position?: number;
    }) => updateCannedResponse(id, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["canned-responses"] });
    },
  });
}

export function useDeleteCannedResponse() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteCannedResponse,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["canned-responses"] });
    },
  });
}

export function useRecordCannedResponseUse() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: recordCannedResponseUse,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["canned-responses"] });
    },
  });
}
