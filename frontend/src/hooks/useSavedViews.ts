/**
 * React Query hooks for saved view operations.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createSavedView,
  deleteSavedView,
  fetchSavedViews,
  updateSavedView,
} from "@/api/savedViews";
import type { SavedViewFilters } from "@/types";

export function useSavedViews() {
  return useQuery({
    queryKey: ["saved-views"],
    queryFn: fetchSavedViews,
  });
}

export function useCreateSavedView() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: {
      name: string;
      filters: SavedViewFilters;
      is_shared: boolean;
      position?: number;
    }) => createSavedView(data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["saved-views"] });
    },
  });
}

export function useUpdateSavedView() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      id,
      ...data
    }: {
      id: string;
      name?: string;
      filters?: SavedViewFilters;
      is_shared?: boolean;
      position?: number;
    }) => updateSavedView(id, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["saved-views"] });
    },
  });
}

export function useDeleteSavedView() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: deleteSavedView,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["saved-views"] });
    },
  });
}
