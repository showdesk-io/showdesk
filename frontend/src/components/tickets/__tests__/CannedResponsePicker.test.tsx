/**
 * Tests for CannedResponsePicker local state: the search text is seeded
 * from `initialQuery` (and re-seeded when it changes or the picker is
 * reopened), and the highlighted row resets whenever the query changes.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { CannedResponse } from "@/api/cannedResponses";

vi.mock("@/hooks/useCannedResponses", () => ({
  useCannedResponses: () => ({ data: responses }),
}));

import { CannedResponsePicker } from "../CannedResponsePicker";

function makeResponse(id: string, name: string, shortcut: string): CannedResponse {
  return {
    id,
    organization: "org",
    created_by: "user",
    name,
    shortcut,
    body: `${name} body`,
    is_shared: false,
    position: 0,
    usage_count: 0,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

const responses: CannedResponse[] = [
  makeResponse("1", "Greeting", "hello"),
  makeResponse("2", "Goodbye", "bye"),
  makeResponse("3", "Refund policy", "refund"),
];

const onSelect = vi.fn();
const onClose = vi.fn();

function renderPicker(props: { open: boolean; initialQuery?: string }) {
  return render(
    <CannedResponsePicker {...props} onSelect={onSelect} onClose={onClose} />,
  );
}

beforeEach(() => {
  onSelect.mockReset();
  onClose.mockReset();
});

describe("CannedResponsePicker", () => {
  it("renders nothing when closed", () => {
    const { container } = renderPicker({ open: false });
    expect(container).toBeEmptyDOMElement();
  });

  it("seeds the search from initialQuery and focuses the input", async () => {
    renderPicker({ open: true, initialQuery: "ref" });
    const input = screen.getByPlaceholderText(/search templates/i);
    expect(input).toHaveValue("ref");
    expect(screen.getByText("1 result")).toBeInTheDocument();
    await waitFor(() => expect(input).toHaveFocus());
  });

  it("re-seeds the search when initialQuery changes", () => {
    const { rerender } = renderPicker({ open: true, initialQuery: "g" });
    rerender(
      <CannedResponsePicker
        open
        initialQuery="good"
        onSelect={onSelect}
        onClose={onClose}
      />,
    );
    expect(screen.getByPlaceholderText(/search templates/i)).toHaveValue("good");
  });

  it("resets the search when closed and reopened", async () => {
    const user = userEvent.setup();
    const { rerender } = renderPicker({ open: true });
    await user.type(screen.getByPlaceholderText(/search templates/i), "bye");
    const props = { onSelect, onClose, initialQuery: "" };
    rerender(<CannedResponsePicker open={false} {...props} />);
    rerender(<CannedResponsePicker open {...props} />);
    expect(screen.getByPlaceholderText(/search templates/i)).toHaveValue("");
  });

  it("resets the highlighted row when the query changes", async () => {
    const user = userEvent.setup();
    renderPicker({ open: true });
    const input = screen.getByPlaceholderText(/search templates/i);
    await user.click(input);
    await user.keyboard("{ArrowDown}{ArrowDown}");
    await user.type(input, "o");
    await user.keyboard("{Enter}");
    // "o" matches all three; highlight is back on the first row.
    expect(onSelect).toHaveBeenCalledWith(responses[0]);
  });
});
