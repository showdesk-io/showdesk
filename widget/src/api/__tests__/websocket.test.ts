import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeWebSocket } from "../../__tests__/harness";
import { WidgetWebSocket } from "../websocket";

const sockets: FakeWebSocket[] = [];

beforeEach(() => {
  sockets.length = 0;
  FakeWebSocket.autoOpen = false;
  vi.useFakeTimers();
  vi.stubGlobal(
    "WebSocket",
    class extends FakeWebSocket {
      constructor(url: string) {
        super(url);
        sockets.push(this);
      }
    },
  );
});

afterEach(() => {
  FakeWebSocket.autoOpen = true;
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("WidgetWebSocket", () => {
  it("sends heartbeats on an open socket", () => {
    const client = new WidgetWebSocket();
    client.connect("https://api.test/api/v1", "tk", "s1");
    sockets[0]?.open();

    vi.advanceTimersByTime(25_000);

    expect(sockets[0]?.sent).toEqual([JSON.stringify({ type: "ping" })]);
    client.disconnect();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("starts no heartbeat for a socket retired while connecting", () => {
    const client = new WidgetWebSocket();
    const onChange = vi.fn();
    client.onConnectionChange = onChange;
    client.connect("https://api.test/api/v1", "tk", "s1");
    const retired = sockets[0];

    client.disconnect();
    retired?.open();

    expect(retired?.closed).toBe(true);
    expect(onChange).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(60_000);
    expect(retired?.sent).toEqual([]);
  });

  it("doesn't let a retired socket's opening disturb the one replacing it", () => {
    const client = new WidgetWebSocket();
    client.connect("https://api.test/api/v1", "tk", "s1");
    const retired = sockets[0];
    client.disconnect();
    client.connect("https://api.test/api/v1", "tk", "s2");
    sockets[1]?.open();

    retired?.open();
    vi.advanceTimersByTime(25_000);

    expect(sockets[1]?.sent).toHaveLength(1);
    client.disconnect();
    expect(vi.getTimerCount()).toBe(0);
  });
});
