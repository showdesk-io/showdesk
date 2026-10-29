import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useDebouncedCheck } from "../useDebouncedCheck";

interface Props {
  input: string;
  enabled: boolean;
}

const check = vi.fn<(input: string) => Promise<string>>();

function setup(initial: Props) {
  return renderHook(
    ({ input, enabled }: Props) => useDebouncedCheck(input, enabled, 300, check),
    { initialProps: initial },
  );
}

/** Advance the debounce window and flush the resolved check promise. */
async function flush(ms = 300) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  check.mockReset();
  check.mockImplementation(async (input) => `ok:${input}`);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useDebouncedCheck", () => {
  it("runs the check only after the debounce delay", async () => {
    const { result } = setup({ input: "acme", enabled: true });
    expect(result.current).toBeNull();
    await flush(299);
    expect(check).not.toHaveBeenCalled();
    await flush(1);
    expect(check).toHaveBeenCalledWith("acme");
    expect(result.current).toBe("ok:acme");
  });

  it("only checks the latest input when it changes quickly", async () => {
    const { result, rerender } = setup({ input: "a", enabled: true });
    await flush(100);
    rerender({ input: "ac", enabled: true });
    await flush(100);
    rerender({ input: "acm", enabled: true });
    await flush();
    expect(check).toHaveBeenCalledTimes(1);
    expect(check).toHaveBeenCalledWith("acm");
    expect(result.current).toBe("ok:acm");
  });

  it("keeps the previous result while a new input is pending", async () => {
    const { result, rerender } = setup({ input: "acme", enabled: true });
    await flush();
    rerender({ input: "acme2", enabled: true });
    expect(result.current).toBe("ok:acme");
    await flush();
    expect(result.current).toBe("ok:acme2");
  });

  it("does not check while disabled", async () => {
    const { result } = setup({ input: "acme", enabled: false });
    await flush();
    expect(check).not.toHaveBeenCalled();
    expect(result.current).toBeNull();
  });

  it("clears the result immediately when disabled and does not resurface it", async () => {
    const { result, rerender } = setup({ input: "acme", enabled: true });
    await flush();
    expect(result.current).toBe("ok:acme");

    rerender({ input: "acme", enabled: false });
    expect(result.current).toBeNull();

    check.mockImplementation(async () => "fresh");
    rerender({ input: "acme", enabled: true });
    expect(result.current).toBeNull();
    await flush();
    expect(result.current).toBe("fresh");
  });

  it("resets the result to null when the check fails", async () => {
    const { result, rerender } = setup({ input: "acme", enabled: true });
    await flush();
    check.mockRejectedValueOnce(new Error("network"));
    rerender({ input: "acme2", enabled: true });
    await flush();
    expect(result.current).toBeNull();
  });
});
