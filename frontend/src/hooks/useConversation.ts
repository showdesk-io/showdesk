/**
 * React Query hooks for the public conversation page.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ConversationError,
  fetchConversation,
  postConversationAttachment,
  postConversationMessage,
  renewConversationLink,
} from "@/api/conversation";

/** The page has no real-time: it polls, only while visible. */
export const CONVERSATION_POLL_MS = 15_000;

function conversationKey(token: string) {
  return ["conversation", token];
}

/** An answer about the link itself, which asking again won't change. */
function isFinal(error: unknown): boolean {
  return (
    error instanceof ConversationError && error.status >= 400 && error.status < 500
  );
}

export function useConversation(token: string) {
  return useQuery({
    queryKey: conversationKey(token),
    queryFn: () => fetchConversation(token),
    enabled: !!token,
    retry: (failures, error) => !isFinal(error) && failures < 2,
    refetchInterval: (query) =>
      isFinal(query.state.error) ? false : CONVERSATION_POLL_MS,
    // React Query pauses the interval while `document.visibilityState` is hidden.
    refetchIntervalInBackground: false,
  });
}

export function useSendConversationMessage(token: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: string) => postConversationMessage(token, body),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: conversationKey(token) }),
  });
}

export function useSendConversationAttachment(token: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => postConversationAttachment(token, file),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: conversationKey(token) }),
  });
}

export function useRenewConversationLink(token: string) {
  return useMutation({ mutationFn: () => renewConversationLink(token) });
}
