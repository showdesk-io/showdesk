import { test, expect } from "@playwright/test";

/**
 * E2E tests for API health and basic endpoints.
 *
 * Verifies the backend API is running and accessible through the proxy.
 */

test.describe("API Health", () => {
  test("API root returns 200 or 401", async ({ request }) => {
    const response = await request.get("/api/v1/");
    // API root should be reachable (even if auth required)
    expect([200, 401, 403]).toContain(response.status());
  });

  test("widget_submit rejects missing token", async ({ request }) => {
    const response = await request.post("/api/v1/tickets/widget_submit/", {
      data: { title: "Test" },
    });
    expect(response.status()).toBe(401);
  });

  test("widget_submit rejects invalid token", async ({ request }) => {
    const response = await request.post("/api/v1/tickets/widget_submit/", {
      data: { title: "Test" },
      headers: { "X-Widget-Token": "00000000-0000-0000-0000-000000000000" },
    });
    expect(response.status()).toBe(401);
  });

  test("static assets are served (widget.js)", async ({ request }) => {
    const response = await request.get("/widget.js");
    expect(response.status()).toBe(200);
    const contentType = response.headers()["content-type"] || "";
    expect(contentType).toMatch(/javascript/);
  });

  test("django admin is accessible", async ({ request }) => {
    const response = await request.get("/admin/login/");
    expect(response.status()).toBe(200);
  });
});
