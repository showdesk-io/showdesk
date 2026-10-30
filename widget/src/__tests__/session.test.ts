/**
 * The session the widget holds, and what happens to the view when the identity changes:
 * login, logout, another user, requests overtaking each other, failures.
 */

import { afterEach, describe, expect, it } from "vitest";
import {
  boot,
  bubbles,
  historyItem,
  openHistoryTab,
  panelText,
  pressSend,
  sendText,
  storedId,
  teardown,
  tick,
} from "./harness";

afterEach(teardown);

const CONFIG = { token: "tk", apiUrl: "/x" };
const USER_A = { ...CONFIG, user: { id: "a", hash: "ha" } };

describe("starting up", () => {
  it("makes one POST when the panel opens during init", async () => {
    const b = await boot();
    b.server.delay = 30;
    b.widget.init({ token: "tk", apiUrl: "https://api.test/api/v1" });
    b.widget.open();
    await tick(120);
    expect(b.posts()).toHaveLength(1);
  });

  it("forwards the user and company fields", async () => {
    const b = await boot();
    b.widget.init({
      ...CONFIG,
      user: { id: 42, hash: "h", email: "a@b.c", emailHash: "eh", traits: { plan: "pro" } },
      company: { id: 7, name: "Acme", domain: "acme.io", traits: { t: 1 }, hash: "ch" },
    });
    await tick();
    expect(b.posts()[0]?.body).toEqual({
      external_user_id: "42",
      user_hash: "h",
      email: "a@b.c",
      email_hash: "eh",
      traits: { plan: "pro" },
      company: { id: 7, name: "Acme", domain: "acme.io", traits: { t: 1 } },
      company_hash: "ch",
    });
  });

  it("reads data-user-email-hash", async () => {
    const b = await boot();
    const tag = document.createElement("script");
    tag.dataset.token = "tk";
    tag.dataset.userId = "u1";
    tag.dataset.userHash = "h";
    tag.dataset.userEmailHash = "eh";
    tag.type = "text/plain";
    tag.setAttribute("src", "https://x.test/widget.js");
    document.body.appendChild(tag);
    b.widget.init({ apiUrl: "/x" });
    await tick();
    expect(b.posts()[0]?.body.email_hash).toBe("eh");
  });

  it("works again after a reset", async () => {
    const b = await boot();
    b.widget.init(USER_A);
    await tick();
    b.widget.reset();
    b.widget.init(CONFIG);
    await tick();
    expect(b.posts().at(-1)?.body.session_id).toBeUndefined();
    expect(storedId()).toBe("anon-1");
  });
});

describe("login", () => {
  it("carries an anonymous conversation on under the identified session", async () => {
    const b = await boot();
    b.widget.init(CONFIG);
    b.widget.open();
    await tick();
    expect(storedId()).toBe("anon-1");
    await sendText("hello");
    expect(b.sent()).toHaveLength(1);

    b.widget.setUser({ id: "u1", hash: "h1", emailHash: "eh" }, { id: "c1", name: "Acme", hash: "ch" });
    await tick(40);

    expect(b.posts().at(-1)?.body).toEqual({
      session_id: "anon-1",
      external_user_id: "u1",
      user_hash: "h1",
      email_hash: "eh",
      company: { id: "c1", name: "Acme" },
      company_hash: "ch",
    });
    expect(storedId()).toBe("sess-u1");
    expect(b.sockets.at(-1)?.url).toContain("session=sess-u1");
    expect(b.sockets.at(-2)?.closed).toBe(true);
    expect(b.conversations().at(-1)?.session).toBe("sess-u1");
    expect(b.histories().at(-1)?.session).toBe("sess-u1");
    expect(bubbles()).toHaveLength(1);
    expect(bubbles()[0]?.textContent).toContain("hello");
  });

  it("keeps only the newest session when it comes during init", async () => {
    const b = await boot();
    b.server.delay = 30;
    b.widget.init(CONFIG);
    b.widget.setUser({ id: "u1", hash: "h1" });
    b.widget.open();
    await tick(150);
    expect(b.posts()).toHaveLength(2);
    expect(storedId()).toBe("sess-u1");
    expect(b.sockets).toHaveLength(1);
  });

  it("clears another user's view at once, even when refused", async () => {
    const b = await boot({
      session: (c) =>
        c.body.user_hash === "bad" ? { status: 403, data: { error: "Invalid user_hash." } } : null,
    });
    b.widget.init(USER_A);
    b.widget.open();
    await tick();
    await sendText("secret of a");
    expect(bubbles()).toHaveLength(1);

    b.widget.setUser({ id: "b", hash: "bad" });
    expect(bubbles()).toHaveLength(0);
    await tick();
    expect(storedId()).toBe("sess-a");
    expect(b.sockets.at(-1)?.closed).toBe(true);

    b.widget.setUser({ id: "b", hash: "hb" });
    await tick();
    expect(storedId()).toBe("sess-b");
    expect(b.conversations()).toHaveLength(0);
    expect(b.sockets.at(-1)?.closed).toBe(false);
    expect(b.sockets.at(-1)?.url).toContain("sess-b");
  });

  it("leaves the session alone on a name without a hash, for an anonymous visitor", async () => {
    const b = await boot();
    b.widget.init(CONFIG);
    await tick();
    const before = b.posts().length;
    b.widget.setUser({ name: "Ann", email: "a@b.c" });
    await tick();
    expect(b.posts()).toHaveLength(before);
    expect(storedId()).toBe("anon-1");
    expect(document.getElementById("showdesk-widget-container")).not.toBeNull();
  });
});

describe("logout", () => {
  it.each([
    ["no argument", undefined],
    ["null", null],
    ["empty", {}],
    ["name only", { name: "x" }],
    ["id only", { id: "a" }],
  ])("restarts anonymously: %s", async (_label, arg) => {
    const b = await boot();
    b.widget.init(USER_A);
    b.widget.open();
    await tick();
    await sendText("secret of a");
    expect(bubbles()).toHaveLength(1);
    const oldSocket = b.sockets.at(-1);
    const before = b.posts().length;

    b.widget.setUser(arg);

    expect(storedId()).toBeNull();
    expect(bubbles()).toHaveLength(0);
    expect(document.getElementById("showdesk-widget-container")).not.toBeNull();
    expect(document.getElementById("sd-panel")).not.toBeNull();
    expect(oldSocket?.closed).toBe(true);

    await tick();
    expect(b.posts()).toHaveLength(before + 1);
    expect(b.posts().at(-1)?.body.session_id).toBeUndefined();
    expect(b.posts().at(-1)?.body.user_hash).toBeUndefined();
    expect(storedId()).toBe("anon-1");
    expect(b.sockets.at(-1)?.closed).toBe(false);
    expect(b.sockets.at(-1)?.url).toContain("session=anon-1");
    expect(b.histories().at(-1)?.session).toBe("anon-1");

    const sentBefore = b.sent().length;
    await sendText("hello anon");
    expect(b.sent()).toHaveLength(sentBefore + 1);
    expect(b.sent().at(-1)?.session).toBe("anon-1");
    expect(b.sent().at(-1)?.body.ticket_id).toBeUndefined();
  });

  it("then a login: identified, one POST each, nothing of the first user", async () => {
    const b = await boot();
    b.widget.init(USER_A);
    b.widget.open();
    await tick();
    await sendText("secret of a");
    b.widget.setUser();
    await tick();
    const before = b.posts().length;

    b.widget.setUser({ id: "b", hash: "hb" });
    await tick();

    expect(b.posts()).toHaveLength(before + 1);
    expect(b.posts().at(-1)?.body).toEqual({
      session_id: "anon-1",
      external_user_id: "b",
      user_hash: "hb",
    });
    expect(storedId()).toBe("sess-b");
    expect(b.sockets.at(-1)?.closed).toBe(false);
    expect(b.sockets.at(-1)?.url).toContain("sess-b");
    expect(bubbles()).toHaveLength(0);

    b.widget.setUser();
    await tick();
    expect(storedId()).toBe("anon-2");
  });

  it("then a login while the anonymous answer is late: stays identified", async () => {
    const b = await boot();
    b.widget.init(USER_A);
    b.widget.open();
    await tick();
    b.server.delay = 30;
    b.widget.setUser();
    b.widget.setUser({ id: "b", hash: "hb" });
    await tick(120);
    expect(storedId()).toBe("sess-b");
    expect(b.sockets.at(-1)?.url).toContain("sess-b");
    expect(b.openSockets()).toHaveLength(1);
    expect(b.posts().at(-1)?.body.session_id).toBeUndefined();
  });

  it("twice in a row, then the panel opened: one POST", async () => {
    const b = await boot();
    b.widget.init(USER_A);
    await tick();
    b.server.delay = 30;
    const before = b.posts().length;
    b.widget.setUser();
    b.widget.setUser(null);
    b.widget.open();
    await tick(120);
    expect(b.posts()).toHaveLength(before + 1);
    expect(storedId()).toBe("anon-1");
    expect(b.openSockets()).toHaveLength(1);
  });

  it("on every render: one restart only", async () => {
    const b = await boot();
    b.widget.init(USER_A);
    await tick();
    const before = b.posts().length;
    for (let i = 0; i < 4; i++) {
      b.widget.setUser();
      await tick();
    }
    expect(b.posts()).toHaveLength(before + 1);
    expect(storedId()).toBe("anon-1");
    expect(b.sockets.at(-1)?.closed).toBe(false);
  });

  it("during init: the first session is dropped, the anonymous one kept", async () => {
    const b = await boot();
    b.server.delay = 30;
    localStorage.setItem("showdesk_session_id", "sess-a");
    b.widget.init(USER_A);
    b.widget.setUser();
    await tick(120);
    expect(b.posts().at(-1)?.body.session_id).toBeUndefined();
    expect(storedId()).toBe("anon-1");
    expect(b.sockets).toHaveLength(1);
    expect(b.sockets[0]?.url).toContain("anon-1");
  });

  it("during init, with no stored id: no socket for the first user", async () => {
    const b = await boot();
    b.server.delay = 30;
    b.widget.init(USER_A);
    b.widget.setUser();
    await tick(100);
    expect(storedId()).toBe("anon-1");
    expect(b.sockets).toHaveLength(1);
    expect(b.sockets[0]?.url).toContain("anon-1");
  });

  it("before the login answers: still restarts", async () => {
    const b = await boot();
    b.widget.init(CONFIG);
    await tick();
    b.server.delay = 30;
    b.widget.setUser({ id: "a", hash: "ha" });
    b.widget.setUser();
    await tick(120);
    expect(b.posts().at(-1)?.body.user_hash).toBeUndefined();
    expect(b.posts().at(-1)?.body.session_id).toBeUndefined();
    expect(storedId()).toBe("anon-2");
  });

  it("after a refused hash restarts: the app did log someone in", async () => {
    const b = await boot({
      session: (c) =>
        c.body.user_hash === "bad" ? { status: 403, data: { error: "Invalid" } } : null,
    });
    b.widget.init({ ...CONFIG, user: { id: "a", hash: "bad" } });
    await tick();
    const before = b.posts().length;
    b.widget.setUser();
    await tick();
    expect(b.posts()).toHaveLength(before + 1);
  });

  it("keeps late answers for the first user out of the anonymous view", async () => {
    let fetched = 0;
    const b = await boot({
      history: { "sess-a": [historyItem("t9", "secret", "open", 2)] },
      conversation: () => {
        fetched += 1;
        return {
          status: 200,
          data: {
            ticket_id: "t9",
            reference: "T-9",
            status: "open",
            messages: [
              {
                id: "m9",
                ticket: "t9",
                body: "secret of a",
                body_type: "text",
                sender_type: "agent",
                sender_name: "",
                attachments: [],
                created_at: "2026-01-01T00:00:00Z",
              },
            ],
          },
        };
      },
    });
    b.widget.init(USER_A);
    await tick();
    b.server.delay = 30;
    b.widget.open(); // Fetches the unread conversation
    b.widget.setUser(); // Logs out before it answers
    await tick(150);
    expect(fetched).toBe(1);
    expect(bubbles()).toHaveLength(0);
    expect(document.body.textContent).not.toContain("secret");
    expect(document.querySelector(".sd-empty-state")).not.toBeNull();
  });

  it("doesn't let a message in flight set a ticket on the new session", async () => {
    const b = await boot();
    b.widget.init(USER_A);
    b.widget.open();
    await tick();
    b.server.delay = 30;
    pressSend("x");
    b.widget.setUser();
    await tick(120);
    b.server.delay = 0;
    await sendText("hello anon");
    expect(b.sent().at(-1)?.session).toBe("anon-1");
    expect(b.sent().at(-1)?.body.ticket_id).toBeUndefined();
  });

  it("commits a pending delete under the session that asked for it", async () => {
    const b = await boot();
    b.widget.init(USER_A);
    b.widget.open();
    await tick();
    await sendText("secret of a");
    const del = document.querySelector<HTMLElement>(
      "[data-message-id] .sd-msg-delete, [data-message-id] button",
    );
    expect(del).not.toBeNull();
    del?.click();
    if (!document.getElementById("sd-delete-toast")) {
      document
        .querySelector<HTMLElement>(".sd-msg-delete-confirm, [data-message-id] .sd-delete-confirm")
        ?.click();
    }
    expect(document.getElementById("sd-delete-toast")).not.toBeNull();

    b.widget.setUser();

    expect(document.getElementById("sd-delete-toast")).toBeNull();
    const deletes = b.calls.filter((c) => c.method === "DELETE");
    expect(deletes).toHaveLength(1);
    expect(deletes[0]?.session).toBe("sess-a");
    await tick();
    expect(bubbles()).toHaveLength(0);
  });

  it("takes the first user's list off the history tab", async () => {
    const b = await boot({ history: { "sess-a": [historyItem("t9", "secret")] } });
    b.widget.init(USER_A);
    b.widget.open();
    await tick();
    openHistoryTab();
    await tick();
    expect(panelText()).toContain("secret");

    b.widget.setUser();
    expect(panelText()).not.toContain("secret");
    await tick();
    expect(panelText()).not.toContain("secret");
  });

  it("that fails stays clean, and reopening the panel tries again", async () => {
    let fail = false;
    const b = await boot({ session: () => (fail ? { status: 500, data: {} } : null) });
    b.widget.init(USER_A);
    b.widget.open();
    await tick();

    fail = true;
    b.widget.setUser();
    await tick();
    expect(storedId()).toBeNull();
    expect(document.getElementById("sd-panel")).not.toBeNull();

    fail = false;
    document.querySelector<HTMLElement>(".sd-panel-close")?.click();
    b.widget.open();
    await tick();
    expect(storedId()).toBe("anon-1");
    expect(b.sockets.at(-1)?.url).toContain("anon-1");

    b.widget.open();
    await tick();
    expect(b.posts().filter((p) => !p.body.user_hash)).toHaveLength(2);
  });
});

describe("reset", () => {
  it("removes the widget", async () => {
    const b = await boot();
    b.widget.init(USER_A);
    b.widget.open();
    await tick();
    const before = b.posts().length;
    b.widget.reset();
    await tick();
    expect(storedId()).toBeNull();
    expect(document.getElementById("showdesk-widget-container")).toBeNull();
    expect(b.sockets.at(-1)?.closed).toBe(true);
    expect(b.posts()).toHaveLength(before);
  });

  it("during a restart: nothing comes back", async () => {
    const b = await boot();
    b.widget.init(USER_A);
    await tick();
    b.server.delay = 30;
    b.widget.setUser();
    b.widget.reset();
    await tick(100);
    expect(storedId()).toBeNull();
    expect(document.getElementById("showdesk-widget-container")).toBeNull();
  });
});

describe("setUser without an identity, on an anonymous visitor", () => {
  it.each([
    ["no argument", undefined],
    ["null", null],
    ["empty", {}],
  ])("leaves the session and conversation alone: %s", async (_label, arg) => {
    const b = await boot();
    b.widget.init(CONFIG);
    b.widget.open();
    await tick();
    await sendText("my question");
    expect(bubbles()).toHaveLength(1);
    const socket = b.sockets.at(-1);
    const posts = b.posts().length;
    const histories = b.histories().length;

    for (let i = 0; i < 3; i++) {
      b.widget.setUser(arg);
      await tick();
    }

    expect(b.posts()).toHaveLength(posts);
    expect(b.histories()).toHaveLength(histories);
    expect(storedId()).toBe("anon-1");
    expect(bubbles()).toHaveLength(1);
    expect(socket?.closed).toBe(false);
    expect(b.sockets.at(-1)).toBe(socket);

    await sendText("still here");
    expect(b.sent().at(-1)?.session).toBe("anon-1");
    expect(b.sent().at(-1)?.body.ticket_id).toBe("t1");
  });

  it("right after init: the stored session is resumed", async () => {
    const b = await boot();
    b.server.delay = 30;
    localStorage.setItem("showdesk_session_id", "anon-stored");
    b.widget.init(CONFIG);
    b.widget.setUser();
    await tick(120);
    expect(b.posts()).toHaveLength(1);
    expect(b.posts()[0]?.body.session_id).toBe("anon-stored");
    expect(storedId()).toBe("anon-stored");
    expect(b.sockets).toHaveLength(1);
  });

  it("clears a name given without a hash, the session untouched", async () => {
    const b = await boot();
    b.widget.init(CONFIG);
    await tick();
    b.widget.setUser({ name: "Ann" });
    await tick();
    const before = b.posts().length;
    b.widget.setUser();
    await tick();
    expect(b.posts()).toHaveLength(before);
    expect(storedId()).toBe("anon-1");
    expect(b.sockets.at(-1)?.closed).toBe(false);
  });
});
