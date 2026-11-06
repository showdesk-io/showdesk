/**
 * The contact form offered to an anonymous visitor after their first message, and what
 * saving it does: the session gets the contact, and the history offers the email code.
 */

import { afterEach, describe, expect, it } from "vitest";
import {
  boot,
  historyItem,
  openChatTab,
  openHistoryTab,
  panelText,
  sendText,
  teardown,
  tick,
  type Booted,
  type Call,
} from "./harness";

afterEach(teardown);

const CONFIG = { token: "tk", apiUrl: "/x" };
const BANNER = "Have earlier conversations by email?";

const nudge = () => document.querySelector<HTMLElement>(".sd-contact-nudge");
const nudges = () => document.querySelectorAll(".sd-contact-nudge");
const banner = () => document.querySelector<HTMLElement>(".sd-email-proof");
const nudgeButton = (label: string) =>
  Array.from(document.querySelectorAll<HTMLButtonElement>(".sd-contact-nudge button")).find(
    (b) => b.textContent?.includes(label),
  );
const patches = (b: Booted) =>
  b.calls.filter((c) => c.url.includes("widget_session") && c.method === "PATCH");

/** What the backend answers to a contact update, as it does with or without inbound mail. */
function contactAnswer(offered: boolean) {
  return (call: Call) =>
    call.method === "PATCH"
      ? {
          status: 200,
          data: {
            session_id: "anon-1",
            name: call.body.name,
            email: call.body.email,
            external_user_id: "",
            email_proof_offered: offered,
          },
        }
      : null;
}

async function openWidget(config: object = CONFIG, offered = true): Promise<Booted> {
  const b = await boot({ session: contactAnswer(offered) });
  b.widget.init(config as typeof CONFIG);
  b.widget.open();
  await tick();
  return b;
}

async function switchTabsAndBack(): Promise<void> {
  openHistoryTab();
  await tick();
  openChatTab();
  await tick();
}

async function saveContact(name: string, email: string): Promise<void> {
  nudgeButton("Add info")?.click();
  const [nameInput, emailInput] = Array.from(
    document.querySelectorAll<HTMLInputElement>(".sd-contact-nudge input"),
  );
  nameInput!.value = name;
  emailInput!.value = email;
  nudgeButton("Save")?.click();
  await tick();
}

describe("the contact nudge", () => {
  it("isn't there before the first message", async () => {
    await openWidget();
    expect(nudge()).toBeNull();
  });

  it("appears once the first message is sent", async () => {
    await openWidget();
    await sendText("hello");
    expect(nudge()?.isConnected).toBe(true);
    expect(nudge()?.textContent).toContain("Add your info");
  });

  it("is there once, whatever follows", async () => {
    await openWidget();
    await sendText("hello");
    await sendText("again");
    await switchTabsAndBack();
    expect(nudges()).toHaveLength(1);
  });

  it("stays through a tab switch", async () => {
    await openWidget();
    await sendText("hello");
    await switchTabsAndBack();
    expect(nudge()?.isConnected).toBe(true);
  });

  it("lets its form be opened after a tab switch", async () => {
    await openWidget();
    await sendText("hello");
    await switchTabsAndBack();
    nudgeButton("Add info")?.click();
    const form = document.querySelector<HTMLElement>(".sd-nudge-form");
    expect(form?.style.display).toBe("flex");
  });

  it("goes for good when dismissed", async () => {
    await openWidget();
    await sendText("hello");
    nudgeButton("Not now")?.click();
    expect(nudge()).toBeNull();
    await sendText("again");
    await switchTabsAndBack();
    expect(nudge()).toBeNull();
  });

  it("isn't offered to a visitor whose email is known", async () => {
    await openWidget({ ...CONFIG, user: { email: "a@x.io" } });
    await sendText("hello");
    expect(nudge()).toBeNull();
  });
});

describe("saving the contact", () => {
  it("updates the session, and the nudge goes for good", async () => {
    const b = await openWidget();
    await sendText("hello");
    await saveContact("Ann", "ann@x.io");

    expect(patches(b)).toHaveLength(1);
    expect(patches(b)[0]?.body).toEqual({ name: "Ann", email: "ann@x.io" });
    expect(patches(b)[0]?.session).toBe("anon-1");
    expect(nudge()).toBeNull();
    await switchTabsAndBack();
    expect(nudge()).toBeNull();
  });

  it("refuses an address without an @", async () => {
    const b = await openWidget();
    await sendText("hello");
    await saveContact("Ann", "ann");
    expect(patches(b)).toHaveLength(0);
    expect(nudge()?.isConnected).toBe(true);
  });

  it("brings the email code banner when the backend offers it", async () => {
    await openWidget(CONFIG, true);
    await sendText("hello");
    await saveContact("Ann", "ann@x.io");
    openHistoryTab();
    await tick();
    expect(banner()?.textContent).toContain(BANNER);
  });

  it("doesn't when the backend doesn't", async () => {
    await openWidget(CONFIG, false);
    await sendText("hello");
    await saveContact("Ann", "ann@x.io");
    openHistoryTab();
    await tick();
    expect(banner()).toBeNull();
  });
});

describe("switching tabs", () => {
  it("renders the tab once", async () => {
    const b = await openWidget();
    const before = b.histories().length;
    openHistoryTab();
    await tick();
    expect(b.histories()).toHaveLength(before + 1);
  });
});

describe("the history open when the contact is saved", () => {
  it("shows the banner once the backend offers it", async () => {
    const b = await openWidget(CONFIG, true);
    await sendText("hello");
    b.server.delay = 30;
    await saveContact("Ann", "ann@x.io");
    openHistoryTab();
    await tick(0);
    expect(banner()).toBeNull();

    await tick(150);

    expect(banner()?.textContent).toContain(BANNER);
  });
});

describe("the history opened before the session is there", () => {
  it("shows the conversations and the banner once it is", async () => {
    const b = await boot({
      history: { "anon-1": [historyItem("h1", "Earlier question", "open")] },
      session: () => ({
        status: 201,
        data: {
          session_id: "anon-1",
          name: "",
          email: "a@x.io",
          external_user_id: "",
          email_proof_offered: true,
        },
      }),
    });
    b.server.delay = 30;
    b.widget.init({ ...CONFIG, user: { email: "a@x.io" } });
    b.widget.open();
    openHistoryTab();
    await tick(0);
    expect(banner()).toBeNull();

    await tick(150);

    expect(panelText()).toContain("Earlier question");
    expect(banner()?.textContent).toContain(BANNER);
  });
});
