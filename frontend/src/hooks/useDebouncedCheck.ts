/**
 * Debounced live check of a text input against an async validator (e.g.
 * "is this slug available?").
 *
 * - While ``enabled``, the check runs ``delayMs`` after ``input`` last
 *   changed; the previous result stays visible until the new one arrives.
 * - When ``enabled`` turns false the result is cleared immediately, so a
 *   stale answer never resurfaces when the check is re-enabled.
 * - A rejected check resets the result to ``null``.
 *
 * ``check`` should be referentially stable (a module-level API function).
 */

import { useEffect, useState } from "react";

export function useDebouncedCheck<T>(
  input: string,
  enabled: boolean,
  delayMs: number,
  check: (input: string) => Promise<T>,
): T | null {
  const [result, setResult] = useState<T | null>(null);

  // Clear the result as soon as the check gets disabled. Adjusting state
  // while rendering (instead of in an effect) avoids an extra commit with
  // the stale value — see react.dev "You Might Not Need an Effect".
  const [wasEnabled, setWasEnabled] = useState(enabled);
  if (wasEnabled !== enabled) {
    setWasEnabled(enabled);
    if (!enabled) setResult(null);
  }

  useEffect(() => {
    if (!enabled) return;
    const handle = window.setTimeout(() => {
      check(input)
        .then(setResult)
        .catch(() => setResult(null));
    }, delayMs);
    return () => window.clearTimeout(handle);
  }, [input, enabled, delayMs, check]);

  return result;
}
