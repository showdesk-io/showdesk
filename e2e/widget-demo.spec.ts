import { test, expect } from "@playwright/test";

/**
 * E2E tests for the Showdesk widget demo page.
 *
 * These tests exercise the full flow: loading the widget demo,
 * initializing the widget with an API token, and submitting a ticket.
 *
 * Prerequisites:
 *   - Full dev stack running (docker compose up)
 *   - Database seeded (python dev.py seed)
 */

// Get the org API token from the backend before tests run
let apiToken: string;

test.beforeAll(async ({ request }) => {
  // Use the Django API to get the org token via a seeded admin user
  // We'll use the widget_submit endpoint to validate the token works
  // For now, fetch directly from the seed output or env
  apiToken = process.env.SHOWDESK_API_TOKEN || "";

  if (!apiToken) {
    // Try to get token from the API by checking the demo page
    const response = await request.get("/widget-demo");
    expect(response.status()).toBe(200);
    // If no token env var, we'll type it manually in tests or skip
  }
});

test.describe("Widget Demo Page", () => {
  test("loads the widget demo page", async ({ page }) => {
    await page.goto("/widget-demo");
    await expect(page).toHaveTitle(/Acme Corp.*Widget Demo/);
    await expect(page.locator("h1")).toContainText("Widget Demo");
  });

  test("shows API token input and Load Widget button", async ({ page }) => {
    await page.goto("/widget-demo");
    await expect(page.getByPlaceholder("paste your org API token")).toBeVisible();
    await expect(page.getByRole("button", { name: "Load Widget" })).toBeVisible();
  });

  test("shows navigation links", async ({ page }) => {
    await page.goto("/widget-demo");
    await expect(page.getByText("Acme Corp", { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Settings > Widget" })).toBeVisible();
    await expect(page.getByRole("link", { name: "agent dashboard" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Mailpit" })).toBeVisible();
  });

  test("shows feature cards", async ({ page }) => {
    await page.goto("/widget-demo");
    await expect(page.getByText("Screen Recording")).toBeVisible();
    await expect(page.getByText("Video Support")).toBeVisible();
    await expect(page.getByText("Zero Install")).toBeVisible();
  });
});

test.describe("Widget Loading", () => {
  test("widget.js is served correctly", async ({ request }) => {
    const response = await request.get("/widget.js");
    expect(response.status()).toBe(200);
    const body = await response.text();
    expect(body).toContain("Showdesk");
  });

  test("loads widget with valid token", async ({ page }) => {
    test.skip(!apiToken, "SHOWDESK_API_TOKEN env var not set");

    await page.goto("/widget-demo");
    await page.getByPlaceholder("paste your org API token").fill(apiToken);
    await page.getByRole("button", { name: "Load Widget" }).click();

    await expect(page.getByText("Widget loaded!")).toBeVisible();
    await expect(page.getByRole("button", { name: "Open support widget" })).toBeVisible();
  });

  test("opens the support form", async ({ page }) => {
    test.skip(!apiToken, "SHOWDESK_API_TOKEN env var not set");

    await page.goto("/widget-demo");
    await page.getByPlaceholder("paste your org API token").fill(apiToken);
    await page.getByRole("button", { name: "Load Widget" }).click();
    await expect(page.getByText("Widget loaded!")).toBeVisible();

    await page.getByRole("button", { name: "Open support widget" }).click();

    await expect(page.getByText("How can we help you today?")).toBeVisible();
    await expect(page.getByLabel("Your name")).toBeVisible();
    await expect(page.getByLabel("Email")).toBeVisible();
    await expect(page.getByLabel("Subject")).toBeVisible();
    await expect(page.getByLabel("Details")).toBeVisible();
    await expect(page.getByRole("button", { name: "Record Screen" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Camera" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Submit Ticket" })).toBeVisible();
  });

  test("submits a ticket successfully", async ({ page }) => {
    test.skip(!apiToken, "SHOWDESK_API_TOKEN env var not set");

    await page.goto("/widget-demo");
    await page.getByPlaceholder("paste your org API token").fill(apiToken);
    await page.getByRole("button", { name: "Load Widget" }).click();
    await expect(page.getByText("Widget loaded!")).toBeVisible();

    await page.getByRole("button", { name: "Open support widget" }).click();
    await expect(page.getByText("How can we help you today?")).toBeVisible();

    await page.getByLabel("Your name").fill("E2E Test User");
    await page.getByLabel("Email").fill("e2e@test.example");
    await page.getByLabel("Subject").fill("E2E test ticket");
    await page.getByLabel("Details").fill("This ticket was created by Playwright e2e tests.");

    await page.getByRole("button", { name: "Submit Ticket" }).click();

    await expect(page.getByText("Ticket submitted!")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Reference: SD-\d+/)).toBeVisible();
  });

  test("closes the widget form", async ({ page }) => {
    test.skip(!apiToken, "SHOWDESK_API_TOKEN env var not set");

    await page.goto("/widget-demo");
    await page.getByPlaceholder("paste your org API token").fill(apiToken);
    await page.getByRole("button", { name: "Load Widget" }).click();
    await expect(page.getByText("Widget loaded!")).toBeVisible();

    await page.getByRole("button", { name: "Open support widget" }).click();
    await expect(page.getByText("How can we help you today?")).toBeVisible();

    await page.getByRole("button", { name: "Close" }).click();
    await expect(page.getByText("How can we help you today?")).not.toBeVisible();
  });
});
