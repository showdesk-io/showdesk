/**
 * React Query hooks for the email channel's mailboxes and their log of received mail.
 */

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createMailbox,
  fetchMailboxes,
  fetchMailboxInbound,
  regenerateMailboxAddress,
  replayInboundEmail,
  updateMailbox,
  type MailboxCreate,
  type MailboxUpdate,
} from "@/api/mailboxes";

const MAILBOXES = ["mailboxes"] as const;

export function useMailboxes() {
  return useQuery({ queryKey: MAILBOXES, queryFn: fetchMailboxes });
}

function useInvalidatingMutation<T>(mutationFn: (variables: T) => Promise<unknown>) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: MAILBOXES });
    },
  });
}

export function useCreateMailbox() {
  return useInvalidatingMutation((data: MailboxCreate) => createMailbox(data));
}

export function useUpdateMailbox() {
  return useInvalidatingMutation(({ id, ...data }: { id: string } & MailboxUpdate) =>
    updateMailbox(id, data),
  );
}

export function useRegenerateMailboxAddress() {
  return useInvalidatingMutation((id: string) => regenerateMailboxAddress(id));
}

export function useMailboxInbound(mailboxId: string, page: number) {
  return useQuery({
    queryKey: [...MAILBOXES, mailboxId, "inbound", page],
    queryFn: () => fetchMailboxInbound(mailboxId, page),
    placeholderData: keepPreviousData,
  });
}

/** Refreshes the mailbox's log: the mail leaves it, unless it fails again. */
export function useReplayInboundEmail(mailboxId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (inboundId: string) => replayInboundEmail(inboundId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: [...MAILBOXES, mailboxId, "inbound"] });
    },
  });
}
