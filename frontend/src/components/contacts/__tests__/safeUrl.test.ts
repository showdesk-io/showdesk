import { describe, expect, it } from "vitest";
import { safeHttpUrl } from "../safeUrl";

describe("safeHttpUrl", () => {
  it.each(["https://acme.io/a?b=1", "http://acme.io/"])("accepts %s", (url) => {
    expect(safeHttpUrl(url)).toBe(url);
  });

  it.each([
    "javascript:alert(1)",
    "JaVaScRiPt:alert(1)",
    " javascript:alert(1)",
    "java\tscript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "vbscript:x",
    "file:///etc/passwd",
    "//evil.test/a",
    "/relative",
    "acme.io",
    "",
    null,
    undefined,
    42,
  ])("refuses %j", (url) => {
    expect(safeHttpUrl(url)).toBeNull();
  });
});
