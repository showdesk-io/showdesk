/**
 * Tests for the useKeyboardShortcuts hook. Pins the contract:
 *   - fires the matching handler on a key
 *   - skips events when typing into inputs / textareas / contenteditable
 *   - skips events with cmd/ctrl/alt modifiers (single-letter shortcuts only)
 *   - opt-out via { enabled: false }
 *   - cleanup removes the listener
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { useKeyboardShortcuts } from "../useKeyboardShortcuts";


function press(
  key: string,
  init: KeyboardEventInit & { target?: Element } = {},
): boolean {
  const event = new KeyboardEvent("keydown", {
    key,
    bubbles: true,
    cancelable: true,
    ...init,
  });
  if (init.target) {
    init.target.dispatchEvent(event);
  } else {
    document.dispatchEvent(event);
  }
  return event.defaultPrevented;
}

afterEach(() => {
  document.body.innerHTML = "";
});


describe("useKeyboardShortcuts", () => {
  it("fires the handler matching the pressed key", () => {
    const onJ = vi.fn();
    renderHook(() => useKeyboardShortcuts({ j: onJ }));

    press("j");
    expect(onJ).toHaveBeenCalledTimes(1);
  });

  it("preventDefaults the event when a handler matches", () => {
    renderHook(() => useKeyboardShortcuts({ x: () => {} }));
    expect(press("x")).toBe(true);
  });

  it("does not fire when the target is an <input>", () => {
    const onJ = vi.fn();
    renderHook(() => useKeyboardShortcuts({ j: onJ }));

    const input = document.createElement("input");
    document.body.appendChild(input);
    input.focus();
    press("j", { target: input });

    expect(onJ).not.toHaveBeenCalled();
  });

  it("does not fire when the target is a <textarea>", () => {
    const onJ = vi.fn();
    renderHook(() => useKeyboardShortcuts({ j: onJ }));

    const ta = document.createElement("textarea");
    document.body.appendChild(ta);
    ta.focus();
    press("j", { target: ta });

    expect(onJ).not.toHaveBeenCalled();
  });

  it("does not fire when contenteditable element is focused", () => {
    const onJ = vi.fn();
    renderHook(() => useKeyboardShortcuts({ j: onJ }));

    const div = document.createElement("div");
    div.setAttribute("contenteditable", "true");
    document.body.appendChild(div);
    press("j", { target: div });

    expect(onJ).not.toHaveBeenCalled();
  });

  it("does not fire on Cmd/Ctrl/Alt-modified events", () => {
    const onR = vi.fn();
    renderHook(() => useKeyboardShortcuts({ r: onR }));

    press("r", { metaKey: true });
    press("r", { ctrlKey: true });
    press("r", { altKey: true });
    expect(onR).not.toHaveBeenCalled();

    press("r");
    expect(onR).toHaveBeenCalledTimes(1);
  });

  it("does fire on Shift-modified events (e.g. Shift + ?)", () => {
    const onHelp = vi.fn();
    renderHook(() => useKeyboardShortcuts({ "?": onHelp }));

    press("?", { shiftKey: true });
    expect(onHelp).toHaveBeenCalledTimes(1);
  });

  it("opts out cleanly when enabled=false", () => {
    const onJ = vi.fn();
    renderHook(() => useKeyboardShortcuts({ j: onJ }, { enabled: false }));

    press("j");
    expect(onJ).not.toHaveBeenCalled();
  });

  it("removes the listener on unmount", () => {
    const onJ = vi.fn();
    const { unmount } = renderHook(() => useKeyboardShortcuts({ j: onJ }));

    press("j");
    expect(onJ).toHaveBeenCalledTimes(1);

    unmount();
    press("j");
    expect(onJ).toHaveBeenCalledTimes(1); // not called again
  });

  it("uses the latest handler ref without re-binding listeners on re-render", () => {
    const first = vi.fn();
    const second = vi.fn();

    const { rerender } = renderHook(
      ({ map }) => useKeyboardShortcuts(map),
      { initialProps: { map: { j: first } } },
    );

    press("j");
    expect(first).toHaveBeenCalledTimes(1);

    rerender({ map: { j: second } });
    press("j");
    expect(first).toHaveBeenCalledTimes(1);
    expect(second).toHaveBeenCalledTimes(1);
  });
});
