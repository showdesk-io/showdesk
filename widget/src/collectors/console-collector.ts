export interface ConsoleEntry {
  level: "error" | "warning";
  message: string;
  source: string;
  timestamp: string;
}

const MAX_ENTRIES = 50;
const MAX_MESSAGE_LENGTH = 500;

let entries: ConsoleEntry[] = [];
let installed = false;

export function installConsoleCollector(): void {
  if (installed) return;
  installed = true;

  const originalError = console.error;
  const originalWarn = console.warn;

  console.error = (...args: unknown[]) => {
    pushEntry("error", args);
    originalError.apply(console, args);
  };

  console.warn = (...args: unknown[]) => {
    pushEntry("warning", args);
    originalWarn.apply(console, args);
  };

  window.addEventListener("error", (event) => {
    pushEntry("error", [event.message], eventSource(event));
  });

  window.addEventListener("unhandledrejection", (event) => {
    const message =
      event.reason instanceof Error
        ? event.reason.message
        : String(event.reason);
    pushEntry("error", [message]);
  });
}

function pushEntry(
  level: ConsoleEntry["level"],
  args: unknown[],
  source = "",
): void {
  const message = args
    .map((a) => (a instanceof Error ? a.message : String(a)))
    .join(" ")
    .slice(0, MAX_MESSAGE_LENGTH);

  entries.push({
    level,
    message,
    source,
    timestamp: new Date().toISOString(),
  });

  if (entries.length > MAX_ENTRIES) {
    entries = entries.slice(-MAX_ENTRIES);
  }
}

function eventSource(event: ErrorEvent): string {
  if (event.filename) {
    return `${event.filename}:${event.lineno}:${event.colno}`;
  }
  return "";
}

export function getConsoleEntries(): ConsoleEntry[] {
  return [...entries];
}

export function clearConsoleEntries(): void {
  entries = [];
}
