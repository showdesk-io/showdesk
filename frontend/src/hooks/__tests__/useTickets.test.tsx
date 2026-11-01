/**
 * Tests for which cached queries a ticket mutation leaves stale, on a real QueryClient.
 */

import { QueryClient, QueryClientProvider, type QueryKey } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { apiClient } from "@/api/client";
import { useResolveTicket } from "../useTickets";

vi.mock("@/api/client", () => ({
  apiClient: { post: vi.fn() },
}));

describe("resolving a ticket", () => {
  it("also refreshes the timelines showing its status", async () => {
    const cached: QueryKey[] = [
      ["ticket", "t1"],
      ["tickets", {}],
      ["contact", "c1", "tickets"],
      ["company", "co1", "tickets"],
    ];
    const queryClient = new QueryClient();
    for (const key of cached) queryClient.setQueryData(key, { cached: true });
    vi.mocked(apiClient.post).mockResolvedValue({ data: { id: "t1" } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useResolveTicket(), { wrapper });
    await result.current.mutateAsync("t1");

    for (const key of cached) {
      expect(queryClient.getQueryState(key)?.isInvalidated).toBe(true);
    }
  });
});
