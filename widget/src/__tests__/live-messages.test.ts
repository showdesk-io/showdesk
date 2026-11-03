/** Messages arriving over the WebSocket on the open conversation. */

import { afterEach, describe, expect, it } from "vitest";
import { boot, bubbles, pressSend, sendText, teardown, tick, type Booted } from "./harness";

afterEach(teardown);

const CONFIG = { token: "tk", apiUrl: "/x" };

function deliver(
  b: Booted,
  id: string,
  senderType: string,
  body: string,
  attachments: unknown[] = [],
): void {
  const socket = b.openSockets().at(-1);
  socket?.onmessage?.({
    data: JSON.stringify({
      event: "message.created",
      ticket_id: "t1",
      message_id: id,
      body,
      body_type: "text",
      sender_type: senderType,
      sender_name: "",
      attachments,
      created_at: "2026-01-01T00:01:00Z",
    }),
  });
}

async function bootOnConversation(): Promise<Booted> {
  const b = await boot();
  b.widget.init(CONFIG);
  b.widget.open();
  await tick();
  await sendText("first");
  return b;
}

const texts = () => Array.from(bubbles()).map((el) => el.textContent ?? "");

describe("a user message from elsewhere", () => {
  it("shows at once, as the customer wrote it by email or on the page", async () => {
    const b = await bootOnConversation();

    deliver(b, "mail-1", "user", "Sent from my phone");
    await tick();

    expect(texts().some((text) => text.includes("Sent from my phone"))).toBe(true);
    expect(bubbles()).toHaveLength(2);
  });

  it("isn't shown twice when it's the widget's own", async () => {
    const b = await bootOnConversation();

    // The event of a message already displayed under its id.
    deliver(b, "m1", "user", "first");
    await tick();
    expect(bubbles()).toHaveLength(1);

    // And one arriving before the answer of the request that sent it.
    b.server.delay = 50;
    pressSend("second");
    await tick(10);
    deliver(b, "m2", "user", "second");
    await tick(100);

    expect(bubbles()).toHaveLength(2);
    expect(texts().filter((text) => text.includes("second"))).toHaveLength(1);
  });
});

describe("an agent's reply with files", () => {
  it("shows its files as it arrives", async () => {
    const b = await bootOnConversation();

    deliver(b, "a-1", "agent", "Here is the invoice", [
      {
        id: "f1",
        file: "https://files.example.com/invoice.pdf",
        filename: "invoice.pdf",
        content_type: "application/pdf",
        file_size: 1200,
      },
    ]);
    await tick();

    const link = document.querySelector<HTMLAnchorElement>(
      '[data-message-id="a-1"] a[href="https://files.example.com/invoice.pdf"]',
    );
    expect(link?.textContent).toContain("invoice.pdf");
  });
});
