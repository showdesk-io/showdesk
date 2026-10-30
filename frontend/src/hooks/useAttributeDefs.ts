/**
 * React Query hooks for custom attribute definitions.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createAttributeDef,
  fetchAttributeDefs,
  updateAttributeDef,
  type AttributeDefCreate,
  type AttributeDefUpdate,
} from "@/api/attributeDefs";
import type { AttributeDefEntity } from "@/types";

export function useAttributeDefs(entity: AttributeDefEntity) {
  return useQuery({
    queryKey: ["attributeDefs", entity],
    queryFn: () => fetchAttributeDefs(entity),
  });
}

export function useCreateAttributeDef(entity: AttributeDefEntity) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: AttributeDefCreate) => createAttributeDef(entity, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["attributeDefs", entity] });
    },
  });
}

export function useUpdateAttributeDef(entity: AttributeDefEntity) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, ...data }: { id: string } & AttributeDefUpdate) =>
      updateAttributeDef(entity, id, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["attributeDefs", entity] });
    },
  });
}
