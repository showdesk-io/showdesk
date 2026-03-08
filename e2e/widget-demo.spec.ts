import { test, expect, Page } from "@playwright/test";

/**
 * E2E tests for the Showdesk widget demo page.
 *
 * These tests exercise the full wizard flow: loading the widget demo,
 * initializing the widget with an API token, and navigating through the
 * multi-step wizard (qualification -> capture -> contact -> confirmation).
 *
 * Prerequisites:
 *   - Full dev stack running (docker compose up)
 *   - Database seeded (python dev.py seed)
 */

// Get the org API token from the backend before tests run
let apiToken: string;

test.beforeAll(async ({ request }) => {
  apiToken = process.env.SHOWDESK_API_TOKEN || "";

  if (!apiToken) {
    // Try to get token from the API by checking the demo page
    const response = await request.get("/widget-demo");
    expect(response.status()).toBe(200);
  }
});

/**
 * Helper: loads the widget demo page and initialises the widget with the API token.
 * Returns after the widget button is visible.
 */
async function loadWidget(page: Page): Promise<void> {
  await page.goto("/widget-demo");
  await page.getByPlaceholder("paste your org API token").fill(apiToken);
  await page.getByRole("button", { name: "Load Widget" }).click();
  await expect(page.getByText("Widget loaded!")).toBeVisible();
  await expect(page.getByRole("button", { name: "Open support widget" })).toBeVisible();
}

/**
 * Helper: opens the widget modal and waits for the qualification step.
 */
async function openWidget(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Open support widget" }).click();
  // The wizard opens on the qualification step with the title "How can we help?"
  await expect(page.locator(".sd-wizard-step")).toBeVisible();
  await expect(page.locator("h3").filter({ hasText: "How can we help?" })).toBeVisible();
}

// ---------------------------------------------------------------------------
// Demo page basics (no token needed)
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Widget loading
// ---------------------------------------------------------------------------

test.describe("Widget Loading", () => {
  test("widget.js is served correctly", async ({ request }) => {
    const response = await request.get("/widget.js");
    expect(response.status()).toBe(200);
    const body = await response.text();
    expect(body).toContain("Showdesk");
  });

  test("loads widget with valid token", async ({ page }) => {
    test.skip(!apiToken, "SHOWDESK_API_TOKEN env var not set");
    await loadWidget(page);
  });
});

// ---------------------------------------------------------------------------
// Wizard — Qualification step
// ---------------------------------------------------------------------------

test.describe("Wizard Qualification Step", () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!apiToken, "SHOWDESK_API_TOKEN env var not set");
    await loadWidget(page);
    await openWidget(page);
  });

  test("shows qualification step with issue type buttons", async ({ page }) => {
    // Step dots should be visible
    await expect(page.locator(".sd-step-dots")).toBeVisible();

    // Four issue type buttons should be visible
    const issueButtons = page.locator(".sd-issue-type-btn");
    await expect(issueButtons).toHaveCount(4);

    // Verify labels
    await expect(page.getByText("Bug / Problem")).toBeVisible();
    await expect(page.getByText("I can't find / understand")).toBeVisible();
    await expect(page.getByText("Suggestion")).toBeVisible();
    await expect(page.getByText("Other")).toBeVisible();
  });

  test("selecting 'Bug' shows follow-up question", async ({ page }) => {
    await page.getByText("Bug / Problem").click();

    // Bug follow-up: "Is the problem visible on screen?"
    await expect(page.locator("h3").filter({ hasText: "Is the problem visible on screen?" })).toBeVisible();
    await expect(page.getByText("Yes, I can see it")).toBeVisible();
    await expect(page.getByText("No, it's an internal error")).toBeVisible();
  });

  test("selecting 'Question' skips follow-up and goes to capture", async ({ page }) => {
    await page.getByText("I can't find / understand").click();

    // Should go directly to capture step
    await expect(page.locator("h3").filter({ hasText: "Describe your issue" })).toBeVisible();
    await expect(page.locator(".sd-capture-textarea")).toBeVisible();
  });

  test("selecting 'Suggestion' skips follow-up and goes to capture", async ({ page }) => {
    await page.getByText("Suggestion").click();

    await expect(page.locator("h3").filter({ hasText: "Describe your issue" })).toBeVisible();
    await expect(page.locator(".sd-capture-textarea")).toBeVisible();
  });

  test("selecting 'Other' skips follow-up and goes to capture", async ({ page }) => {
    await page.getByText("Other").click();

    await expect(page.locator("h3").filter({ hasText: "Describe your issue" })).toBeVisible();
    await expect(page.locator(".sd-capture-textarea")).toBeVisible();
  });

  test("bug follow-up 'Yes' advances to capture step", async ({ page }) => {
    await page.getByText("Bug / Problem").click();
    await page.getByText("Yes, I can see it").click();

    await expect(page.locator("h3").filter({ hasText: "Describe your issue" })).toBeVisible();
    await expect(page.locator(".sd-capture-textarea")).toBeVisible();
  });

  test("bug follow-up 'No' advances to capture step", async ({ page }) => {
    await page.getByText("Bug / Problem").click();
    await page.getByText("No, it's an internal error").click();

    await expect(page.locator("h3").filter({ hasText: "Describe your issue" })).toBeVisible();
  });

  test("bug follow-up has Back button returning to issue types", async ({ page }) => {
    await page.getByText("Bug / Problem").click();
    await expect(page.getByText("Is the problem visible on screen?")).toBeVisible();

    await page.getByText("◀ Back").click();

    // Back to qualification
    await expect(page.locator("h3").filter({ hasText: "How can we help?" })).toBeVisible();
    await expect(page.locator(".sd-issue-type-btn")).toHaveCount(4);
  });
});

// ---------------------------------------------------------------------------
// Wizard — Capture step
// ---------------------------------------------------------------------------

test.describe("Wizard Capture Step", () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!apiToken, "SHOWDESK_API_TOKEN env var not set");
    await loadWidget(page);
    await openWidget(page);
    // Navigate to capture step via "Question" (simplest path, no follow-up)
    await page.getByText("I can't find / understand").click();
    await expect(page.locator(".sd-capture-textarea")).toBeVisible();
  });

  test("shows textarea with issue-type-specific placeholder", async ({ page }) => {
    // "Question" placeholder: "What are you trying to do?"
    await expect(page.locator(".sd-capture-textarea")).toHaveAttribute(
      "placeholder",
      "What are you trying to do?",
    );
  });

  test("Continue button is disabled when textarea is empty", async ({ page }) => {
    const continueBtn = page.locator(".sd-submit-btn", { hasText: "Continue" });
    await expect(continueBtn).toBeDisabled();
  });

  test("Continue button enables when text is entered", async ({ page }) => {
    await page.locator(".sd-capture-textarea").fill("I need help with something");
    const continueBtn = page.locator(".sd-submit-btn", { hasText: "Continue" });
    await expect(continueBtn).toBeEnabled();
  });

  test("Back button returns to qualification step", async ({ page }) => {
    await page.getByText("◀ Back").click();
    await expect(page.locator("h3").filter({ hasText: "How can we help?" })).toBeVisible();
  });

  test("clicking Continue advances to contact step", async ({ page }) => {
    await page.locator(".sd-capture-textarea").fill("I need help with something");
    await page.locator(".sd-submit-btn", { hasText: "Continue" }).click();

    // Should show contact form (anonymous flow — no pre-filled identity)
    await expect(page.locator("h3").filter({ hasText: "Your contact details" })).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Wizard — Contact step
// ---------------------------------------------------------------------------

test.describe("Wizard Contact Step", () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!apiToken, "SHOWDESK_API_TOKEN env var not set");
    await loadWidget(page);
    await openWidget(page);
    // Navigate: Question -> fill description -> Continue
    await page.getByText("I can't find / understand").click();
    await page.locator(".sd-capture-textarea").fill("Test description for contact step");
    await page.locator(".sd-submit-btn", { hasText: "Continue" }).click();
    await expect(page.locator("h3").filter({ hasText: "Your contact details" })).toBeVisible();
  });

  test("shows name and email fields", async ({ page }) => {
    await expect(page.getByPlaceholder("Your name")).toBeVisible();
    await expect(page.getByPlaceholder("you@example.com")).toBeVisible();
  });

  test("Send button is present", async ({ page }) => {
    await expect(page.locator(".sd-submit-btn", { hasText: "Send" })).toBeVisible();
  });

  test("Back button returns to capture step", async ({ page }) => {
    await page.getByText("◀ Back").click();
    await expect(page.locator("h3").filter({ hasText: "Describe your issue" })).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Wizard — Full submission flow
// ---------------------------------------------------------------------------

test.describe("Wizard Full Submission", () => {
  test("submits a ticket through the full wizard (question flow)", async ({ page }) => {
    test.skip(!apiToken, "SHOWDESK_API_TOKEN env var not set");

    await loadWidget(page);
    await openWidget(page);

    // Step 1: Qualification — select "Question"
    await page.getByText("I can't find / understand").click();

    // Step 2: Capture — fill description
    await expect(page.locator(".sd-capture-textarea")).toBeVisible();
    await page.locator(".sd-capture-textarea").fill("This ticket was created by Playwright E2E tests.");
    await page.locator(".sd-submit-btn", { hasText: "Continue" }).click();

    // Step 3: Contact — fill name and email
    await expect(page.locator("h3").filter({ hasText: "Your contact details" })).toBeVisible();
    await page.getByPlaceholder("Your name").fill("E2E Test User");
    await page.getByPlaceholder("you@example.com").fill("e2e@test.example");
    await page.locator(".sd-submit-btn", { hasText: "Send" }).click();

    // Step 4: Confirmation — should show success
    await expect(page.getByText("Message sent!")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Reference: SD-\d+/)).toBeVisible();
  });

  test("submits a ticket through the bug flow (visible)", async ({ page }) => {
    test.skip(!apiToken, "SHOWDESK_API_TOKEN env var not set");

    await loadWidget(page);
    await openWidget(page);

    // Step 1: Qualification — select "Bug" then "Yes, I can see it"
    await page.getByText("Bug / Problem").click();
    await page.getByText("Yes, I can see it").click();

    // Step 2: Capture — fill description, video button should have "Recommended" badge
    await expect(page.locator(".sd-capture-textarea")).toBeVisible();
    await expect(page.locator(".sd-recommended-badge")).toBeVisible();
    await page.locator(".sd-capture-textarea").fill("Bug report: button is not clickable.");
    await page.locator(".sd-submit-btn", { hasText: "Continue" }).click();

    // Step 3: Contact — fill name and email
    await expect(page.locator("h3").filter({ hasText: "Your contact details" })).toBeVisible();
    await page.getByPlaceholder("Your name").fill("E2E Bug Reporter");
    await page.getByPlaceholder("you@example.com").fill("bug@test.example");
    await page.locator(".sd-submit-btn", { hasText: "Send" }).click();

    // Step 4: Confirmation
    await expect(page.getByText("Message sent!")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Reference: SD-\d+/)).toBeVisible();
  });

  test("question flow does not show video option", async ({ page }) => {
    test.skip(!apiToken, "SHOWDESK_API_TOKEN env var not set");

    await loadWidget(page);
    await openWidget(page);

    // Select "Question"
    await page.getByText("I can't find / understand").click();

    // Capture step should NOT show the Video recorder button
    await expect(page.locator(".sd-capture-textarea")).toBeVisible();
    await expect(page.locator(".sd-recorder-btn", { hasText: "Video" })).not.toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Wizard — Confirmation step
// ---------------------------------------------------------------------------

test.describe("Wizard Confirmation", () => {
  test("confirmation screen shows checkmark, reference, and close button", async ({ page }) => {
    test.skip(!apiToken, "SHOWDESK_API_TOKEN env var not set");

    await loadWidget(page);
    await openWidget(page);

    // Fast-path through wizard
    await page.getByText("Other").click();
    await page.locator(".sd-capture-textarea").fill("Confirmation test ticket");
    await page.locator(".sd-submit-btn", { hasText: "Continue" }).click();
    await page.getByPlaceholder("Your name").fill("Confirm User");
    await page.getByPlaceholder("you@example.com").fill("confirm@test.example");
    await page.locator(".sd-submit-btn", { hasText: "Send" }).click();

    // Verify confirmation elements
    await expect(page.getByText("Message sent!")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Reference: SD-\d+/)).toBeVisible();
    await expect(page.locator(".sd-confirmation-checkmark")).toBeVisible();
    await expect(page.getByText("We'll get back to you as soon as possible.")).toBeVisible();

    // Close button should dismiss the modal
    await page.locator(".sd-submit-btn", { hasText: "Close" }).click();
    await expect(page.locator(".sd-wizard-step")).not.toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Widget — Close behaviour
// ---------------------------------------------------------------------------

test.describe("Widget Close", () => {
  test("closes the widget modal with close button", async ({ page }) => {
    test.skip(!apiToken, "SHOWDESK_API_TOKEN env var not set");

    await loadWidget(page);
    await openWidget(page);

    // Close via the X button (aria-label="Close")
    await page.getByRole("button", { name: "Close" }).click();
    await expect(page.locator(".sd-wizard-step")).not.toBeVisible();
  });
});
