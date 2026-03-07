import { test, expect } from "@playwright/test";

/**
 * E2E tests for the authentication flow (OTP-based).
 *
 * Prerequisites:
 *   - Full dev stack running
 *   - Database seeded (admin@showdesk.local exists)
 *   - Mailpit available at /mailpit/
 */

test.describe("Authentication", () => {
  test("login page is accessible", async ({ page }) => {
    await page.goto("/");
    // Should redirect to login
    await expect(page).toHaveURL(/\/login/);
  });

  test("login page shows email input and submit", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByPlaceholder("agent@company.com")).toBeVisible();
    await expect(page.getByRole("button", { name: "Send login code" })).toBeVisible();
  });

  test("unauthenticated access redirects to login", async ({ page }) => {
    await page.goto("/tickets");
    await expect(page).toHaveURL(/\/login/);
  });

  test("unauthenticated access to settings redirects", async ({ page }) => {
    await page.goto("/settings");
    await expect(page).toHaveURL(/\/login/);
  });
});

test.describe("Mailpit", () => {
  test("mailpit is accessible", async ({ page }) => {
    await page.goto("/mailpit/");
    // Mailpit should load (it has its own UI)
    await expect(page).toHaveURL(/\/mailpit/);
  });
});
