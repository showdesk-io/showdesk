/**
 * Lightweight global keyboard-shortcut hook -- no external dependency.
 *
 * Listens at document level; ignores events whose target is a text-entry
 * control or a contenteditable surface so typing in inputs / forms keeps
 * working unchanged. Modifier-only chords (Cmd/Ctrl/Alt) are skipped --
 * we want single-letter shortcuts à la Linear/GitHub. Shift may be
 * required (e.g. ``Shift + ?`` for the help overlay).
 *
 * Usage:
 *   useKeyboardShortcuts({
 *     j: () => setFocus(focus + 1),
 *     k: () => setFocus(focus - 1),
 *     "?": () => setHelpOpen(true),
 *   });
 *
 * Pass ``enabled: false`` to opt a page out without unmounting.
 */

import { useEffect, useRef } from "react";

export type ShortcutHandler = (e: KeyboardEvent) => void;
export type ShortcutMap = Record<string, ShortcutHandler>;

export interface ShortcutOptions {
  enabled?: boolean;
}

function isTextInput(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (target.isContentEditable) return true;
  // Fallback: jsdom does not always reflect the property — also check the
  // attribute directly. Covers ``contenteditable="plaintext-only"`` too.
  const attr = target.getAttribute("contenteditable");
  if (attr !== null && attr !== "false") return true;
  return false;
}

export function useKeyboardShortcuts(
  shortcuts: ShortcutMap,
  options: ShortcutOptions = {},
): void {
  const { enabled = true } = options;
  // Stash the latest map in a ref so handlers don't need to re-bind on
  // every render (parents that pass closures would otherwise thrash).
  const mapRef = useRef<ShortcutMap>(shortcuts);
  mapRef.current = shortcuts;

  useEffect(() => {
    if (!enabled) return;
    const handler = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (isTextInput(e.target)) return;
      const key = e.key;
      const fn = mapRef.current[key];
      if (fn) {
        e.preventDefault();
        fn(e);
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [enabled]);
}
