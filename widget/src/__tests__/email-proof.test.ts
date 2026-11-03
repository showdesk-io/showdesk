/**
 * Proving the session's email by a code to see its conversations by email (§6.2).
 *
 * The banner is the same for any unproven email, whatever is behind it, and a wrong
 * code gets one neutral message whatever the cause.
 */

import { afterEach, describe, expect, it } from "vitest";
import {
  boot,
  bubbles,
  historyItem,
  openHistoryTab,
  panelText,
  teardown,
  tick,
  type Answer,
  type Booted,
  type Call,
} from "./harness";

afterEach(teardown);

const CONFIG = { token: "tk", apiUrl: "/x", user: { email: "a@x.io" } };
const BANNER = "Have earlier conversations by email?";
const WRONG = "That code didn't work. Check it, or get a new one.";

const banner = () => document.querySelector<HTMLElement>(".sd-email-proof");
const button = (label: string) =>
  Array.from(document.querySelectorAll<HTMLButtonElement>(".sd-email-proof button")).find(
    (b) => b.textContent?.includes(label),
  );
const codeInput = () =>
  document.querySelector<HTMLInputElement>(".sd-email-proof input") as HTMLInputElement;

/** Boot with a session offering the code, and answer the two code routes. */
async function bootOffered(
  verify: (call: Call) => Answer = () => ({ status: 200, data: { verified: true } }),
  extra: { email?: string; history?: Record<string, unknown[]> } = {},
): Promise<Booted> {
  const b = await boot({
    history: extra.history,
    session: () => ({
      status: 201,
      data: {
        session_id: "anon-1",
        name: "",
        email: extra.email ?? "a@x.io",
        external_user_id: "",
        email_proof_offered: true,
      },
    }),
  });
  const base = b.server.handler;
  b.server.handler = (call) => {
    if (call.url.includes("widget_email_code")) return { status: 202, data: {} };
    if (call.url.includes("widget_email_verify")) return verify(call);
    return base(call);
  };
  b.widget.init(CONFIG);
  b.widget.open();
  await tick();
  openHistoryTab();
  await tick();
  return b;
}

async function askAndEnter(code: string): Promise<void> {
  button("Get a code")?.click();
  await tick();
  codeInput().value = code;
  codeInput().dispatchEvent(new Event("input"));
  button("Verify")?.click();
  await tick();
}

const codeCalls = (b: Booted) => b.calls.filter((c) => c.url.includes("widget_email_code"));

describe("the email code banner", () => {
  it("shows above the history for an unproven email", async () => {
    await bootOffered();
    expect(banner()?.textContent).toContain(BANNER);
    expect(button("Get a code")).toBeDefined();
  });

  it("isn't there when nothing is offered", async () => {
    const b = await boot();
    b.widget.init(CONFIG);
    b.widget.open();
    await tick();
    openHistoryTab();
    await tick();
    expect(banner()).toBeNull();
  });

  it("asks for a code, and lets a new one be asked for after 60 s", async () => {
    const b = await bootOffered();
    button("Get a code")?.click();
    await tick();
    expect(codeCalls(b)).toHaveLength(1);
    expect(codeCalls(b)[0]?.session).toBe("anon-1");
    expect(codeInput().maxLength).toBe(6);

    expect(button("Resend")?.disabled).toBe(true);
    await tick(60_000);
    expect(button("Resend")?.disabled).toBe(false);
    button("Resend")?.click();
    await tick();
    expect(codeCalls(b)).toHaveLength(2);
  });

  it("shows the address as text", async () => {
    await bootOffered(undefined, { email: '<img src=x onerror="alert(1)">@x.io' });
    button("Get a code")?.click();
    await tick();
    expect(banner()?.querySelector("img")).toBeNull();
    expect(banner()?.textContent).toContain("<img");
  });

  it("says the same of a wrong code and of a proof that didn't hold", async () => {
    const answers: Answer[] = [
      { status: 400, data: { error: "Invalid or expired code." } },
      { status: 200, data: { verified: false } },
      { status: 429, data: {} },
    ];
    await bootOffered(() => answers.shift() as Answer);
    await askAndEnter("123456");
    expect(banner()?.textContent).toContain(WRONG);
    for (const _ of [1, 2]) {
      button("Verify")?.click();
      await tick();
      expect(banner()?.textContent).toContain(WRONG);
      expect(banner()?.querySelectorAll(".sd-email-proof-error")).toHaveLength(1);
    }
  });

  it("refreshes the history once the code is right", async () => {
    let proven = false;
    const b = await bootOffered(
      () => {
        proven = true;
        return { status: 200, data: { verified: true } };
      },
    );
    const base = b.server.handler;
    b.server.handler = (call) =>
      call.url.includes("widget_history") && proven
        ? { status: 200, data: [historyItem("e1", "Invoice question", "open", 1)] }
        : base(call);

    await askAndEnter("123456");

    expect(banner()).toBeNull();
    expect(panelText()).toContain("Invoice question");
    const verify = b.calls.find((c) => c.url.includes("widget_email_verify"));
    expect(verify?.body).toEqual({ code: "123456" });
  });
});

describe("an email-born conversation", () => {
  it("opens and receives replies like any other", async () => {
    const b = await bootOffered(undefined, {
      history: { "anon-1": [historyItem("e1", "Invoice question", "open")] },
    });
    b.server.handler = ((base) => (call: Call) =>
      call.url.includes("widget_conversation")
        ? {
            status: 200,
            data: { ticket_id: "e1", reference: "T-e1", status: "open", messages: [] },
          }
        : base(call))(b.server.handler);

    document.querySelector<HTMLElement>(".sd-history-item")?.click();
    await tick();
    expect(bubbles()).toHaveLength(0);

    b.openSockets()[0]?.onmessage?.({
      data: JSON.stringify({
        event: "message.created",
        ticket_id: "e1",
        message_id: "r1",
        body: "We refunded it",
        sender_type: "agent",
        created_at: "2026-01-01T00:00:00Z",
      }),
    });
    await tick();
    expect(bubbles()).toHaveLength(1);
    expect(panelText()).toContain("We refunded it");
  });
});

describe("after a failed code", () => {
  it("lets a new code be asked for at once", async () => {
    const b = await bootOffered(() => ({ status: 200, data: { verified: false } }));
    await askAndEnter("123456");

    expect(banner()?.textContent).toContain(WRONG);
    expect(button("Get a new code")?.disabled).toBe(false);
    button("Get a new code")?.click();
    await tick();
    expect(codeCalls(b)).toHaveLength(2);
  });
});

describe("a changed email", () => {
  it("drops the code asked for the previous one", async () => {
    const b = await bootOffered();
    button("Get a code")?.click();
    await tick();
    expect(codeInput()).not.toBeNull();

    b.widget.setUser({ email: "b@x.io" });
    await tick();

    expect(banner()?.textContent).toContain(BANNER);
    expect(document.querySelector(".sd-email-proof input")).toBeNull();
  });
});

describe("a conversation seen through the history only", () => {
  const readOnlyConversation = (call: Call): Answer =>
    call.url.includes("widget_conversation")
      ? {
          status: 200,
          data: {
            ticket_id: "o1",
            reference: "T-o1",
            status: "open",
            read_only: true,
            messages: [],
          },
        }
      : { status: 0, data: null };

  async function openOther(b: Booted, answer: (call: Call) => Answer): Promise<void> {
    const base = b.server.handler;
    b.server.handler = (call) => {
      const special = answer(call);
      return special.status ? special : base(call);
    };
    document.querySelector<HTMLElement>(".sd-history-item")?.click();
    await tick();
  }

  const notice = () => document.querySelector<HTMLElement>(".sd-read-only");
  const inputBar = () => document.querySelector<HTMLElement>(".sd-input-bar");

  it("is shown read-only, with a way to start a new conversation", async () => {
    const b = await bootOffered(undefined, {
      history: { "anon-1": [historyItem("o1", "Someone else's", "open")] },
    });
    await openOther(b, readOnlyConversation);

    expect(notice()?.textContent).toContain("can only be read here");
    expect(inputBar()?.style.display).toBe("none");

    Array.from(notice()?.querySelectorAll("button") ?? [])
      .find((el) => el.textContent?.includes("Start a new conversation"))
      ?.click();
    await tick();
    expect(notice()?.style.display).toBe("none");
    expect(inputBar()?.style.display).not.toBe("none");
    expect(bubbles()).toHaveLength(0);
  });

  it("becomes read-only when writing is refused", async () => {
    const b = await bootOffered(undefined, {
      history: { "anon-1": [historyItem("o1", "Someone else's", "open")] },
    });
    await openOther(b, (call) =>
      call.url.includes("widget_message")
        ? { status: 403, data: { error: "read-only" } }
        : { status: 0, data: null },
    );

    const input = document.querySelector("textarea") as HTMLTextAreaElement;
    input.value = "Hello";
    input.dispatchEvent(new Event("input"));
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await tick();

    expect(notice()?.style.display).not.toBe("none");
    expect(inputBar()?.style.display).toBe("none");
  });

  it("is closed for writing when the ticket was closed too long ago", async () => {
    const b = await bootOffered(undefined, {
      history: { "anon-1": [historyItem("o1", "Old one", "closed")] },
    });
    await openOther(b, (call) =>
      call.url.includes("widget_message")
        ? { status: 409, data: { error: "closed" } }
        : { status: 0, data: null },
    );

    const input = document.querySelector("textarea") as HTMLTextAreaElement;
    input.value = "Hello";
    input.dispatchEvent(new Event("input"));
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await tick();

    expect(notice()?.style.display).not.toBe("none");
    expect(notice()?.textContent).toContain("This conversation is closed.");
    expect(notice()?.textContent).toContain("Start a new conversation");
    expect(inputBar()?.style.display).toBe("none");
  });
});

describe("a proven session given another email", () => {
  it("starts again at once, so the previous person's history goes", async () => {
    const b = await bootOffered();
    await askAndEnter("123456");
    expect(banner()).toBeNull();
    const before = b.posts().length;

    b.widget.setUser({ email: "b@x.io" });
    await tick();

    expect(b.posts()).toHaveLength(before + 1);
    expect(b.posts().at(-1)?.body.email).toBe("b@x.io");
    expect(b.posts().at(-1)?.body.session_id).toBe("anon-1");
  });

  it("isn't started again for the same email", async () => {
    const b = await bootOffered();
    await askAndEnter("123456");
    const before = b.posts().length;

    b.widget.setUser({ email: "A@x.io" });
    await tick();

    expect(b.posts()).toHaveLength(before);
  });
});
