/** Sending while there's no session yet, or none to be had. */

import { afterEach, describe, expect, it } from "vitest";
import { boot, bubbles, pressSend, sendText, storedId, teardown, textarea, tick } from "./harness";

afterEach(teardown);

const CONFIG = { token: "tk", apiUrl: "/x" };
const error = () => document.querySelector(".sd-input-error");

/** A widget whose session requests fail until `recover()`. */
async function bootWithoutSession() {
  const state = { fail: true };
  const b = await boot({ session: () => (state.fail ? { status: 503, data: {} } : null) });
  b.widget.init(CONFIG);
  b.widget.open();
  await tick();
  return { ...b, recover: () => (state.fail = false) };
}

describe("sending with no session", () => {
  it("keeps the text and says so when the session can't be had", async () => {
    const b = await bootWithoutSession();
    const before = b.posts().length;

    await sendText("don't lose me");

    expect(b.posts().length).toBeGreaterThan(before);
    expect(b.sent()).toHaveLength(0);
    expect(textarea().value).toBe("don't lose me");
    expect(error()?.textContent).toMatch(/couldn't be sent/i);
    expect(bubbles()).toHaveLength(0);
  });

  it("goes through on the next try, and the error goes", async () => {
    const b = await bootWithoutSession();
    await sendText("don't lose me");

    b.recover();
    await sendText("don't lose me");

    expect(b.sent()).toHaveLength(1);
    expect(b.sent()[0]?.body.body).toBe("don't lose me");
    expect(b.sent()[0]?.session).toBe("anon-1");
    expect(textarea().value).toBe("");
    expect(error()).toBeNull();
    expect(bubbles()).toHaveLength(1);
  });

  it("waits for a session still on its way", async () => {
    const b = await boot();
    b.server.delay = 30;
    b.widget.init(CONFIG);
    b.widget.open();

    pressSend("early");
    expect(textarea().value).toBe("early");
    await tick(150);

    expect(storedId()).toBe("anon-1");
    expect(b.posts()).toHaveLength(1);
    expect(b.sent()).toHaveLength(1);
    expect(b.sent()[0]?.body.body).toBe("early");
    expect(textarea().value).toBe("");
    expect(error()).toBeNull();
  });

  it("waits for the session replacing one that was overtaken", async () => {
    const b = await boot();
    b.server.delay = 30;
    b.widget.init(CONFIG);
    b.widget.open();
    b.widget.setUser({ id: "u1", hash: "h1" });

    pressSend("early");
    await tick(150);

    expect(b.sent()[0]?.session).toBe("sess-u1");
    expect(error()).toBeNull();
  });

  it("doesn't send twice on a double press while waiting", async () => {
    const b = await boot();
    b.server.delay = 30;
    b.widget.init(CONFIG);
    b.widget.open();

    pressSend("early");
    pressSend("early");
    await tick(150);

    expect(b.sent()).toHaveLength(1);
  });

  it("says so for a file too, rather than dropping it", async () => {
    const b = await bootWithoutSession();
    const input = document.querySelector<HTMLInputElement>('input[type="file"]')!;
    const file = new File(["x"], "a.txt", { type: "text/plain" });
    Object.defineProperty(input, "files", { value: [file], configurable: true });

    input.onchange?.(new Event("change"));
    await tick();

    expect(b.sent()).toHaveLength(0);
    expect(error()?.textContent).toMatch(/couldn't be sent/i);
  });
});

describe("sending with a session", () => {
  it("clears the input at once", async () => {
    const b = await boot();
    b.widget.init(CONFIG);
    b.widget.open();
    await tick();

    pressSend("hello");

    expect(textarea().value).toBe("");
    await tick();
    expect(b.sent()).toHaveLength(1);
  });
});
