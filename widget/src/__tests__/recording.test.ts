/** A recording in the page belongs to the session it started on. */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { boot, bubbles, sendText, storedId, teardown, tick } from "./harness";

const CONFIG = { token: "tk", apiUrl: "/x" };
const USER_A = { ...CONFIG, user: { id: "a", hash: "ha" } };
const blob = () => new Blob(["recording"], { type: "video/webm" });

const recorder = vi.hoisted(() => ({
  last: null as null | { onStop: (blob: Blob) => void },
}));

beforeEach(() => {
  vi.doMock("../recorder/screen-recorder", () => ({
    ScreenRecorder: class {
      onStop: (blob: Blob) => void = () => {};
      isAudioEnabled = true;
      micDeviceId = "";
      constructor() {
        recorder.last = this;
      }
      async start() {}
      stop() {}
    },
  }));
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:local" }));
});

afterEach(teardown);

function chooseCapture(label: string): void {
  document.querySelector<HTMLElement>(".sd-input-attach")?.click();
  Array.from(document.querySelectorAll<HTMLElement>(".sd-attach-menu-item"))
    .find((item) => item.textContent?.includes(label))
    ?.click();
}

const startVideo = async () => {
  chooseCapture("Screen capture");
  await tick();
};

describe("a screen recording", () => {
  it("is sent as usual if the session didn't change", async () => {
    const b = await boot();
    b.widget.init(USER_A);
    b.widget.open();
    await tick();
    await sendText("hello");
    await startVideo();

    recorder.last?.onStop(blob());
    await tick();

    expect(b.sent().at(-1)?.session).toBe("sess-a");
    expect(b.sent().at(-1)?.form?.get("ticket_id")).toBe("t1");
    expect(bubbles()).toHaveLength(2);
  });

  it("stays with the user who started it when another logs in", async () => {
    const b = await boot();
    b.widget.init(USER_A);
    b.widget.open();
    await tick();
    await sendText("hello");
    await startVideo();

    b.widget.setUser({ id: "b", hash: "hb" });
    await tick();
    recorder.last?.onStop(blob());
    await tick();

    expect(storedId()).toBe("sess-b");
    expect(b.sent().at(-1)?.session).toBe("sess-a");
    expect(b.sent().at(-1)?.form?.get("ticket_id")).toBe("t1");
    // Nothing of it in the new user's view, nor on their next message.
    expect(bubbles()).toHaveLength(0);
    await sendText("from b");
    expect(b.sent().at(-1)?.session).toBe("sess-b");
    expect(b.sent().at(-1)?.body.ticket_id).toBeUndefined();
  });

  it("stays with the user who started it through a logout", async () => {
    const b = await boot();
    b.widget.init(USER_A);
    b.widget.open();
    await tick();
    await startVideo();

    b.widget.setUser();
    await tick();
    recorder.last?.onStop(blob());
    await tick();

    expect(storedId()).toBe("anon-1");
    expect(b.sent().at(-1)?.session).toBe("sess-a");
    expect(b.sent().at(-1)?.form?.get("ticket_id")).toBeNull();
    expect(bubbles()).toHaveLength(0);
  });

  it("follows a login of the anonymous visitor, whose conversation moved with it", async () => {
    const b = await boot();
    b.widget.init(CONFIG);
    b.widget.open();
    await tick();
    await sendText("hello");
    await startVideo();

    b.widget.setUser({ id: "u1", hash: "h1" });
    await tick();
    recorder.last?.onStop(blob());
    await tick();

    expect(b.sent().at(-1)?.session).toBe("sess-u1");
    expect(b.sent().at(-1)?.form?.get("ticket_id")).toBe("t1");
  });

  it("goes on being sent to its session when that one can't answer in the view", async () => {
    const b = await boot({
      session: (c) =>
        c.body.user_hash === "bad" ? { status: 403, data: { error: "Invalid" } } : null,
    });
    b.widget.init(USER_A);
    b.widget.open();
    await tick();
    await startVideo();

    // Another user, refused: no session at all in the view when the recording ends.
    b.widget.setUser({ id: "b", hash: "bad" });
    await tick();
    recorder.last?.onStop(blob());
    await tick();

    expect(b.sent().at(-1)?.session).toBe("sess-a");
  });
});

describe("an audio recording", () => {
  it("stays with the user who started it", async () => {
    let media: { onstop: () => void; ondataavailable: (e: { data: Blob }) => void } | null = null;
    const track = { stop() {}, enabled: true };
    const stream = { getTracks: () => [track], getAudioTracks: () => [track] };
    vi.stubGlobal("navigator", {
      ...navigator,
      mediaDevices: { getUserMedia: async () => stream },
    });
    vi.stubGlobal(
      "AudioContext",
      class {
        createMediaStreamDestination = () => ({ stream });
        createMediaStreamSource = () => ({ connect() {}, disconnect() {} });
        close = async () => {};
      },
    );
    vi.stubGlobal(
      "MediaRecorder",
      class {
        static isTypeSupported = () => true;
        onstop = () => {};
        ondataavailable = () => {};
        constructor() {
          media = this as never;
        }
        start() {}
        stop() {}
      },
    );

    const b = await boot();
    b.widget.init(USER_A);
    b.widget.open();
    await tick();
    chooseCapture("Audio");
    await tick();

    b.widget.setUser({ id: "b", hash: "hb" });
    await tick();
    media!.ondataavailable({ data: blob() });
    media!.onstop();
    await tick();

    expect(b.sent().at(-1)?.session).toBe("sess-a");
    expect(bubbles()).toHaveLength(0);
  });
});
