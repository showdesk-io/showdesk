/**
 * A contact can be anonymized while its page is open: the API then refuses any write with
 * a 409, and what's on screen is out of date.
 */

import { useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { parseApiError } from "@/api/errors";

/** Returns a handler: true if it was that, said so and refreshed. */
export function useContactConflict(contactId: string): (error: unknown) => boolean {
  const queryClient = useQueryClient();

  return (error) => {
    const { status, message } = parseApiError(error);
    if (status !== 409) return false;
    toast.error(message ?? "This contact has been anonymized.");
    void queryClient.invalidateQueries({ queryKey: ["contact", contactId] });
    return true;
  };
}
