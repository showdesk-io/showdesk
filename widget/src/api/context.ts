/**
 * Automatic technical context capture.
 *
 * Zero friction: all technical information is captured automatically
 * when the widget opens. The user never has to manually report their
 * browser, OS, or screen resolution.
 */

import type { TechnicalContext } from "../types";
import { getConsoleEntries } from "../collectors/console-collector";
import { getNetworkEntries } from "../collectors/network-collector";

export function captureContext(): TechnicalContext {
  const ua = navigator.userAgent;

  return {
    url: window.location.href,
    userAgent: ua,
    os: detectOS(ua),
    browser: detectBrowser(ua),
    screenResolution: `${window.screen.width}x${window.screen.height}`,
    language: navigator.language,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    referrer: document.referrer,
    consoleErrors: getConsoleEntries(),
    networkErrors: getNetworkEntries(),
  };
}

function detectOS(ua: string): string {
  if (ua.includes("Win")) return "Windows";
  if (ua.includes("Mac")) return "macOS";
  if (ua.includes("Linux")) return "Linux";
  if (ua.includes("Android")) return "Android";
  if (ua.includes("iPhone") || ua.includes("iPad")) return "iOS";
  if (ua.includes("CrOS")) return "ChromeOS";
  return "Unknown";
}

function detectBrowser(ua: string): string {
  if (ua.includes("Firefox/")) return "Firefox";
  if (ua.includes("Edg/")) return "Edge";
  if (ua.includes("Chrome/") && !ua.includes("Edg/")) return "Chrome";
  if (ua.includes("Safari/") && !ua.includes("Chrome/")) return "Safari";
  if (ua.includes("Opera/") || ua.includes("OPR/")) return "Opera";
  return "Unknown";
}
