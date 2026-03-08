export interface NetworkEntry {
  method: string;
  url: string;
  status: number;
  duration_ms: number;
  timestamp: string;
}

const MAX_ENTRIES = 50;

let entries: NetworkEntry[] = [];
let installed = false;

export function installNetworkCollector(): void {
  if (installed) return;
  installed = true;

  patchFetch();
  patchXHR();
}

function pushEntry(entry: NetworkEntry): void {
  entries.push(entry);
  if (entries.length > MAX_ENTRIES) {
    entries = entries.slice(-MAX_ENTRIES);
  }
}

function isErrorStatus(status: number): boolean {
  return status >= 400;
}

function patchFetch(): void {
  const originalFetch = window.fetch;

  window.fetch = async function (
    input: RequestInfo | URL,
    init?: RequestInit,
  ): Promise<Response> {
    const method = init?.method?.toUpperCase() || "GET";
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    const start = performance.now();

    try {
      const response = await originalFetch.call(window, input, init);
      if (isErrorStatus(response.status)) {
        pushEntry({
          method,
          url: truncateUrl(url),
          status: response.status,
          duration_ms: Math.round(performance.now() - start),
          timestamp: new Date().toISOString(),
        });
      }
      return response;
    } catch (error) {
      pushEntry({
        method,
        url: truncateUrl(url),
        status: 0,
        duration_ms: Math.round(performance.now() - start),
        timestamp: new Date().toISOString(),
      });
      throw error;
    }
  };
}

function patchXHR(): void {
  const originalOpen = XMLHttpRequest.prototype.open;
  const originalSend = XMLHttpRequest.prototype.send;

  XMLHttpRequest.prototype.open = function (
    method: string,
    url: string | URL,
    ...rest: unknown[]
  ) {
    (this as XHRWithMeta)._sd_method = method.toUpperCase();
    (this as XHRWithMeta)._sd_url =
      typeof url === "string" ? url : url.href;
    return originalOpen.apply(
      this,
      [method, url, ...rest] as Parameters<typeof originalOpen>,
    );
  };

  XMLHttpRequest.prototype.send = function (
    body?: Document | XMLHttpRequestBodyInit | null,
  ) {
    const meta = this as XHRWithMeta;
    const start = performance.now();

    this.addEventListener("loadend", () => {
      if (isErrorStatus(this.status)) {
        pushEntry({
          method: meta._sd_method || "UNKNOWN",
          url: truncateUrl(meta._sd_url || ""),
          status: this.status,
          duration_ms: Math.round(performance.now() - start),
          timestamp: new Date().toISOString(),
        });
      }
    });

    return originalSend.call(this, body);
  };
}

interface XHRWithMeta extends XMLHttpRequest {
  _sd_method?: string;
  _sd_url?: string;
}

function truncateUrl(url: string): string {
  try {
    const parsed = new URL(url, window.location.origin);
    return parsed.pathname;
  } catch {
    return url.slice(0, 200);
  }
}

export function getNetworkEntries(): NetworkEntry[] {
  return [...entries];
}

export function clearNetworkEntries(): void {
  entries = [];
}
