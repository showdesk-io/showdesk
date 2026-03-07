/**
 * Ticket detail page.
 */

import { useParams } from "react-router-dom";
import toast from "react-hot-toast";
import { TicketDetail } from "@/components/tickets/TicketDetail";
import { useTicket, useCreateMessage } from "@/hooks/useTickets";

export function TicketDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: ticket, isLoading, error } = useTicket(id!);
  const createMessage = useCreateMessage(id!);

  const handleSendMessage = (body: string, messageType: string) => {
    createMessage.mutate(
      { body, message_type: messageType },
      {
        onSuccess: () => {
          toast.success("Message sent.");
        },
        onError: () => {
          toast.error("Failed to send message.");
        },
      },
    );
  };

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary-500 border-t-transparent" />
      </div>
    );
  }

  if (error || !ticket) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-gray-500">Ticket not found.</p>
      </div>
    );
  }

  return (
    <TicketDetail
      ticket={ticket}
      onSendMessage={handleSendMessage}
      isSending={createMessage.isPending}
    />
  );
}
