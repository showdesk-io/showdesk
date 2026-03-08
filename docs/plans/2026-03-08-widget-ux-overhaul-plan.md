# Widget UX Overhaul — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform the widget from a simple form into a guided, context-rich support experience with camera PiP, automatic error capture, and user identity.

**Architecture:** The widget (vanilla TypeScript, IIFE bundle) gets a full UI rewrite: wizard flow replaces the single form, a Canvas-based PiP compositor replaces the raw multi-track recorder, and error/network interceptors hook at script load. Backend gets two new Ticket fields and enriched context_metadata. Frontend agent dashboard gets collapsible error panels.

**Tech Stack:** TypeScript (widget), Django/DRF (backend), React/Tailwind (frontend), Canvas API + MediaRecorder (PiP), pytest (backend tests), Playwright (widget E2E)

**Design doc:** `docs/plans/2026-03-08-widget-ux-overhaul-design.md`

---

## Batch 1 — Backend: New Ticket Fields + Serializer

### Task 1.1: Add `issue_type` field to Ticket model

**Files:**
- Modify: `backend/apps/tickets/models.py` (Ticket class, around line 134)
- Create: migration (auto-generated)

**Step 1: Write the failing test**

File: `backend/tests/tickets/test_widget_submit.py` (add to existing test file)

```python
def test_widget_submit_with_issue_type(self):
    """Widget can submit a ticket with an issue_type."""
    response = self.client.post(
        "/api/v1/tickets/widget_submit/",
        data={
            "title": "Button broken",
            "description": "Cannot click submit",
            "requester_name": "Jean",
            "requester_email": "jean@acme.com",
            "issue_type": "bug",
        },
        format="json",
        HTTP_X_WIDGET_TOKEN=self.organization.api_token,
    )
    assert response.status_code == 201
    assert response.data["issue_type"] == "bug"

def test_widget_submit_issue_type_defaults_to_other(self):
    """issue_type defaults to 'other' when not provided."""
    response = self.client.post(
        "/api/v1/tickets/widget_submit/",
        data={
            "title": "Hello",
            "description": "World",
            "requester_name": "Jean",
            "requester_email": "jean@acme.com",
        },
        format="json",
        HTTP_X_WIDGET_TOKEN=self.organization.api_token,
    )
    assert response.status_code == 201
    assert response.data["issue_type"] == "other"
```

**Step 2: Run tests to verify they fail**

Run: `docker compose exec backend pytest tests/tickets/test_widget_submit.py -v -k "issue_type"`
Expected: FAIL — field doesn't exist

**Step 3: Add field to model**

In `backend/apps/tickets/models.py`, inside the Ticket class:

```python
class IssueType(models.TextChoices):
    BUG = "bug", "Bug"
    QUESTION = "question", "Question"
    SUGGESTION = "suggestion", "Suggestion"
    OTHER = "other", "Other"

issue_type = models.CharField(
    max_length=20,
    choices=IssueType.choices,
    default=IssueType.OTHER,
    blank=True,
)
```

**Step 4: Generate and apply migration**

Run: `docker compose exec backend python manage.py makemigrations tickets -n add_issue_type_field`
Run: `docker compose exec backend python manage.py migrate`

**Step 5: Add field to serializers**

In `backend/apps/tickets/serializers.py`:
- Add `"issue_type"` to `TicketSerializer.Meta.fields`
- Add `"issue_type"` to `TicketCreateFromWidgetSerializer.Meta.fields`

**Step 6: Run tests to verify they pass**

Run: `docker compose exec backend pytest tests/tickets/test_widget_submit.py -v -k "issue_type"`
Expected: PASS

**Step 7: Commit**

```bash
git add backend/apps/tickets/models.py backend/apps/tickets/serializers.py backend/apps/tickets/migrations/
git commit -m "feat(tickets): add issue_type field to Ticket model"
```

---

### Task 1.2: Add `external_user_id` field to Ticket model

**Files:**
- Modify: `backend/apps/tickets/models.py`
- Modify: `backend/apps/tickets/serializers.py`
- Create: migration (auto-generated)

**Step 1: Write the failing test**

```python
def test_widget_submit_with_external_user_id(self):
    """Widget can submit a ticket with external_user_id."""
    response = self.client.post(
        "/api/v1/tickets/widget_submit/",
        data={
            "title": "Bug report",
            "description": "Details",
            "requester_name": "Jean",
            "requester_email": "jean@acme.com",
            "external_user_id": "usr_12345",
        },
        format="json",
        HTTP_X_WIDGET_TOKEN=self.organization.api_token,
    )
    assert response.status_code == 201
    assert response.data["external_user_id"] == "usr_12345"

def test_widget_submit_external_user_id_defaults_to_empty(self):
    """external_user_id defaults to empty string."""
    response = self.client.post(
        "/api/v1/tickets/widget_submit/",
        data={
            "title": "Bug",
            "description": "Details",
            "requester_name": "Jean",
            "requester_email": "jean@acme.com",
        },
        format="json",
        HTTP_X_WIDGET_TOKEN=self.organization.api_token,
    )
    assert response.status_code == 201
    assert response.data["external_user_id"] == ""
```

**Step 2: Run tests to verify they fail**

Run: `docker compose exec backend pytest tests/tickets/test_widget_submit.py -v -k "external_user_id"`

**Step 3: Add field to model**

```python
external_user_id = models.CharField(
    max_length=255,
    blank=True,
    default="",
    db_index=True,
    help_text="User ID from the host application, passed via widget init.",
)
```

**Step 4: Generate and apply migration**

Run: `docker compose exec backend python manage.py makemigrations tickets -n add_external_user_id_field`
Run: `docker compose exec backend python manage.py migrate`

**Step 5: Add field to serializers**

Add `"external_user_id"` to both `TicketSerializer.Meta.fields` and `TicketCreateFromWidgetSerializer.Meta.fields`.

**Step 6: Run tests to verify they pass**

Run: `docker compose exec backend pytest tests/tickets/test_widget_submit.py -v -k "external_user_id"`
Expected: PASS

**Step 7: Commit**

```bash
git add backend/apps/tickets/models.py backend/apps/tickets/serializers.py backend/apps/tickets/migrations/
git commit -m "feat(tickets): add external_user_id field for host app user tracking"
```

---

### Task 1.3: Accept enriched context_metadata (console + network errors)

The `context_metadata` field is already a `JSONField` on Ticket. No model change needed — just verify the backend accepts and returns the enriched data, and add a test.

**Files:**
- Test: `backend/tests/tickets/test_widget_submit.py`

**Step 1: Write the failing test**

```python
def test_widget_submit_with_console_and_network_errors(self):
    """Widget can submit enriched context_metadata with console and network errors."""
    context_metadata = {
        "language": "fr-FR",
        "timezone": "Europe/Paris",
        "referrer": "https://app.acme.com/dashboard",
        "console_errors": [
            {
                "level": "error",
                "message": "TypeError: Cannot read property 'id' of undefined",
                "source": "Settings.tsx:142",
                "timestamp": "2026-03-08T10:32:15.123Z",
            }
        ],
        "network_errors": [
            {
                "method": "POST",
                "url": "/api/v1/settings/",
                "status": 500,
                "duration_ms": 234,
                "timestamp": "2026-03-08T10:32:14.456Z",
            }
        ],
    }
    response = self.client.post(
        "/api/v1/tickets/widget_submit/",
        data={
            "title": "Settings crash",
            "description": "Page broke",
            "requester_name": "Jean",
            "requester_email": "jean@acme.com",
            "context_metadata": context_metadata,
        },
        format="json",
        HTTP_X_WIDGET_TOKEN=self.organization.api_token,
    )
    assert response.status_code == 201
    assert len(response.data["context_metadata"]["console_errors"]) == 1
    assert response.data["context_metadata"]["console_errors"][0]["level"] == "error"
    assert len(response.data["context_metadata"]["network_errors"]) == 1
    assert response.data["context_metadata"]["network_errors"][0]["status"] == 500
```

**Step 2: Run test**

Run: `docker compose exec backend pytest tests/tickets/test_widget_submit.py -v -k "console_and_network"`
Expected: Should PASS (JSONField accepts any structure). If it fails, investigate serializer restrictions.

**Step 3: Commit**

```bash
git add backend/tests/tickets/test_widget_submit.py
git commit -m "test(tickets): verify enriched context_metadata with console/network errors"
```

---

### Task 1.4: Run full backend test suite

**Step 1:** Run: `docker compose exec backend pytest -v`
Expected: All tests pass (88+ existing + 5 new)

**Step 2: Commit if any fixups needed**

---

## Batch 2 — Widget: Automatic Context Collectors

### Task 2.1: Console error/warning interceptor

**Files:**
- Create: `widget/src/collectors/console-collector.ts`
- Test: manual via widget demo + Playwright E2E

**Step 1: Create the collector module**

```typescript
// widget/src/collectors/console-collector.ts

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

  // Capture uncaught errors
  window.addEventListener("error", (event) => {
    pushEntry("error", [event.message], eventSource(event));
  });

  // Capture unhandled promise rejections
  window.addEventListener("unhandledrejection", (event) => {
    const message = event.reason instanceof Error
      ? event.reason.message
      : String(event.reason);
    pushEntry("error", [message]);
  });
}

function pushEntry(level: ConsoleEntry["level"], args: unknown[], source = ""): void {
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

  // Circular buffer
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
```

**Step 2: Verify it compiles**

Run: `cd widget && npm run build`
Expected: Build succeeds

**Step 3: Commit**

```bash
git add widget/src/collectors/console-collector.ts
git commit -m "feat(widget): add console error/warning interceptor"
```

---

### Task 2.2: Network error interceptor

**Files:**
- Create: `widget/src/collectors/network-collector.ts`

**Step 1: Create the collector module**

```typescript
// widget/src/collectors/network-collector.ts

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

  window.fetch = async function (input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
    const method = init?.method?.toUpperCase() || "GET";
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
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
  const OriginalXHR = window.XMLHttpRequest;
  const originalOpen = OriginalXHR.prototype.open;
  const originalSend = OriginalXHR.prototype.send;

  OriginalXHR.prototype.open = function (method: string, url: string | URL, ...rest: unknown[]) {
    (this as XMLHttpRequestWithMeta)._sd_method = method.toUpperCase();
    (this as XMLHttpRequestWithMeta)._sd_url = typeof url === "string" ? url : url.href;
    return originalOpen.apply(this, [method, url, ...rest] as Parameters<typeof originalOpen>);
  };

  OriginalXHR.prototype.send = function (body?: Document | XMLHttpRequestBodyInit | null) {
    const meta = this as XMLHttpRequestWithMeta;
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

interface XMLHttpRequestWithMeta extends XMLHttpRequest {
  _sd_method?: string;
  _sd_url?: string;
}

function truncateUrl(url: string): string {
  // Remove query params for privacy, keep path
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
```

**Step 2: Verify it compiles**

Run: `cd widget && npm run build`

**Step 3: Commit**

```bash
git add widget/src/collectors/network-collector.ts
git commit -m "feat(widget): add network error interceptor (fetch + XHR)"
```

---

### Task 2.3: Install collectors at script load

**Files:**
- Modify: `widget/src/widget.ts` (entry point)
- Modify: `widget/src/api/context.ts` (enrich capture)

**Step 1: Install collectors at top of widget.ts**

At the very top of `widget/src/widget.ts`, before any other code:

```typescript
import { installConsoleCollector } from "./collectors/console-collector";
import { installNetworkCollector } from "./collectors/network-collector";

// Install collectors immediately at script load (before init)
installConsoleCollector();
installNetworkCollector();
```

**Step 2: Enrich captureContext() in context.ts**

In `widget/src/api/context.ts`, import collectors and add data to context:

```typescript
import { getConsoleEntries } from "../collectors/console-collector";
import { getNetworkEntries } from "../collectors/network-collector";

// Add to captureContext() return object:
export function captureContext(): TechnicalContext {
  return {
    url: window.location.href,
    userAgent: navigator.userAgent,
    os: detectOS(navigator.userAgent),
    browser: detectBrowser(navigator.userAgent),
    screenResolution: `${window.screen.width}x${window.screen.height}`,
    language: navigator.language,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    referrer: document.referrer,
    consoleErrors: getConsoleEntries(),
    networkErrors: getNetworkEntries(),
  };
}
```

**Step 3: Update TechnicalContext type in types.ts**

Add to `TechnicalContext` interface:

```typescript
import type { ConsoleEntry } from "./collectors/console-collector";
import type { NetworkEntry } from "./collectors/network-collector";

export interface TechnicalContext {
  // ... existing fields ...
  consoleErrors: ConsoleEntry[];
  networkErrors: NetworkEntry[];
}
```

**Step 4: Send enriched data in submit.ts**

In the `submitTicket()` function, update the context_metadata construction to include console and network errors:

```typescript
context_metadata: {
  language: context.language,
  timezone: context.timezone,
  referrer: context.referrer,
  console_errors: context.consoleErrors,
  network_errors: context.networkErrors,
},
```

**Step 5: Build and verify**

Run: `cd widget && npm run build`
Expected: Build succeeds, dist/widget.js updated

**Step 6: Commit**

```bash
git add widget/src/widget.ts widget/src/api/context.ts widget/src/api/submit.ts widget/src/types.ts
git commit -m "feat(widget): install error collectors at script load, enrich context metadata"
```

---

## Batch 3 — Widget: User Identity

### Task 3.1: Add user identity to init() API

**Files:**
- Modify: `widget/src/widget.ts`
- Modify: `widget/src/types.ts`

**Step 1: Extend types**

In `widget/src/types.ts`, add:

```typescript
export interface ShowdeskUserIdentity {
  id?: string;
  name?: string;
  email?: string;
}

// Extend ShowdeskConfig:
export interface ShowdeskConfig {
  // ... existing fields ...
  user?: ShowdeskUserIdentity;
}
```

**Step 2: Update init() to accept user**

In `widget/src/widget.ts`, the `init()` function already reads config. Ensure `user` is stored on the config object. No major change needed — it comes from the config parameter.

Add a `setUser()` public function for late initialization:

```typescript
export function setUser(user: ShowdeskUserIdentity): void {
  if (!currentConfig) {
    console.warn("[Showdesk] Call init() before setUser()");
    return;
  }
  currentConfig.user = user;
}
```

Expose `setUser` on the global `Showdesk` object alongside `init`, `open`, `destroy`.

**Step 3: Build and verify**

Run: `cd widget && npm run build`

**Step 4: Commit**

```bash
git add widget/src/widget.ts widget/src/types.ts
git commit -m "feat(widget): add user identity API (init + setUser)"
```

---

### Task 3.2: Send external_user_id with ticket submission

**Files:**
- Modify: `widget/src/api/submit.ts`
- Modify: `widget/src/ui/modal.ts`

**Step 1: Pass user identity to submitTicket**

In `submit.ts`, add `external_user_id` to the request body:

```typescript
export async function submitTicket(
  config: ShowdeskConfig,
  data: TicketSubmission,
): Promise<TicketResponse> {
  const body = {
    ...data,
    external_user_id: config.user?.id || "",
  };
  // ... rest unchanged
}
```

**Step 2: Pre-fill name/email from identity in modal.ts**

When creating input fields, use config.user values as defaults:

```typescript
const nameInput = /* ... */;
nameInput.value = config.user?.name || "";

const emailInput = /* ... */;
emailInput.value = config.user?.email || "";
```

**Step 3: Build and verify**

Run: `cd widget && npm run build`

**Step 4: Commit**

```bash
git add widget/src/api/submit.ts widget/src/ui/modal.ts
git commit -m "feat(widget): pre-fill contact fields from user identity, send external_user_id"
```

---

## Batch 4 — Widget: Guided Wizard Flow

This is the largest batch. The modal.ts file (~336 lines) gets a complete rewrite into a multi-step wizard.

### Task 4.1: Create wizard state machine

**Files:**
- Create: `widget/src/ui/wizard/wizard-state.ts`

**Step 1: Create the state module**

```typescript
// widget/src/ui/wizard/wizard-state.ts

export type IssueType = "bug" | "question" | "suggestion" | "other";
export type BugVisibility = "visible" | "not_visible" | null;
export type WizardStep = "qualification" | "capture" | "contact" | "sending" | "confirmation";

export interface WizardState {
  step: WizardStep;
  issueType: IssueType | null;
  bugVisibility: BugVisibility;
  description: string;
  requesterName: string;
  requesterEmail: string;
  recordedBlob: Blob | null;
  recordingType: string;
  hasAudio: boolean;
  hasCamera: boolean;
  attachments: File[];
}

export function createInitialState(prefillName = "", prefillEmail = ""): WizardState {
  return {
    step: "qualification",
    issueType: null,
    bugVisibility: null,
    description: "",
    requesterName: prefillName,
    requesterEmail: prefillEmail,
    recordedBlob: null,
    recordingType: "screen",
    hasAudio: false,
    hasCamera: false,
    attachments: [],
  };
}

export interface CaptureOptions {
  showVideo: boolean;
  showScreenshot: boolean;
  showMic: boolean;
  showCamera: boolean;
  videoRecommended: boolean;
}

export function getCaptureOptions(state: WizardState): CaptureOptions {
  switch (state.issueType) {
    case "bug":
      if (state.bugVisibility === "visible") {
        return { showVideo: true, showScreenshot: true, showMic: true, showCamera: true, videoRecommended: true };
      }
      return { showVideo: true, showScreenshot: false, showMic: true, showCamera: false, videoRecommended: false };
    case "question":
      return { showVideo: false, showScreenshot: true, showMic: false, showCamera: false, videoRecommended: false };
    case "suggestion":
      return { showVideo: true, showScreenshot: true, showMic: true, showCamera: true, videoRecommended: false };
    case "other":
    default:
      return { showVideo: true, showScreenshot: true, showMic: true, showCamera: true, videoRecommended: false };
  }
}

export function getTextareaPlaceholder(issueType: IssueType | null): string {
  switch (issueType) {
    case "bug":
      return "What do you see? What did you expect?";
    case "question":
      return "What are you trying to do?";
    case "suggestion":
      return "What would you like to see improved?";
    default:
      return "How can we help?";
  }
}

export function shouldShowFollowUp(issueType: IssueType | null): boolean {
  return issueType === "bug";
}

export function canSkipContact(name: string, email: string): boolean {
  return name.trim().length > 0 && email.trim().length > 0 && email.includes("@");
}
```

**Step 2: Build**

Run: `cd widget && npm run build`

**Step 3: Commit**

```bash
git add widget/src/ui/wizard/wizard-state.ts
git commit -m "feat(widget): add wizard state machine with issue type branching"
```

---

### Task 4.2: Create qualification step UI

**Files:**
- Create: `widget/src/ui/wizard/step-qualification.ts`

**Step 1: Create the qualification step renderer**

```typescript
// widget/src/ui/wizard/step-qualification.ts

import type { IssueType, BugVisibility } from "./wizard-state";
import { shouldShowFollowUp } from "./wizard-state";

interface QualificationResult {
  issueType: IssueType;
  bugVisibility: BugVisibility;
}

export function renderQualificationStep(
  container: HTMLElement,
  onComplete: (result: QualificationResult) => void,
): void {
  container.innerHTML = "";

  const wrapper = document.createElement("div");
  wrapper.className = "sd-wizard-step";

  // Title
  const title = document.createElement("h3");
  title.className = "sd-wizard-title";
  title.textContent = "How can we help?";
  wrapper.appendChild(title);

  // Issue type buttons
  const options: { type: IssueType; icon: string; label: string }[] = [
    { type: "bug", icon: "\uD83D\uDC1B", label: "Bug / Problem" },
    { type: "question", icon: "\u2753", label: "I can't find / understand" },
    { type: "suggestion", icon: "\uD83D\uDCA1", label: "Suggestion" },
    { type: "other", icon: "\u2709\uFE0F", label: "Other" },
  ];

  const grid = document.createElement("div");
  grid.className = "sd-issue-type-grid";

  options.forEach(({ type, icon, label }) => {
    const btn = document.createElement("button");
    btn.className = "sd-issue-type-btn";
    btn.innerHTML = `<span class="sd-issue-type-icon">${icon}</span><span>${label}</span>`;
    btn.addEventListener("click", () => {
      if (shouldShowFollowUp(type)) {
        renderFollowUp(container, type, onComplete);
      } else {
        onComplete({ issueType: type, bugVisibility: null });
      }
    });
    grid.appendChild(btn);
  });

  wrapper.appendChild(grid);
  container.appendChild(wrapper);
}

function renderFollowUp(
  container: HTMLElement,
  issueType: IssueType,
  onComplete: (result: QualificationResult) => void,
): void {
  container.innerHTML = "";

  const wrapper = document.createElement("div");
  wrapper.className = "sd-wizard-step";

  const title = document.createElement("h3");
  title.className = "sd-wizard-title";
  title.textContent = "Is the problem visible on screen?";
  wrapper.appendChild(title);

  const btnYes = document.createElement("button");
  btnYes.className = "sd-followup-btn";
  btnYes.textContent = "Yes, I can see it";
  btnYes.addEventListener("click", () => {
    onComplete({ issueType, bugVisibility: "visible" });
  });

  const btnNo = document.createElement("button");
  btnNo.className = "sd-followup-btn";
  btnNo.textContent = "No, it's an internal error";
  btnNo.addEventListener("click", () => {
    onComplete({ issueType, bugVisibility: "not_visible" });
  });

  const backBtn = document.createElement("button");
  backBtn.className = "sd-back-btn";
  backBtn.textContent = "\u25C0 Back";
  backBtn.addEventListener("click", () => {
    renderQualificationStep(container, onComplete);
  });

  wrapper.appendChild(btnYes);
  wrapper.appendChild(btnNo);
  wrapper.appendChild(backBtn);
  container.appendChild(wrapper);
}
```

**Step 2: Build**

Run: `cd widget && npm run build`

**Step 3: Commit**

```bash
git add widget/src/ui/wizard/step-qualification.ts
git commit -m "feat(widget): add qualification step UI with issue type selection"
```

---

### Task 4.3: Create capture step UI

**Files:**
- Create: `widget/src/ui/wizard/step-capture.ts`

This step renders the description textarea and the available capture tools (video, screenshot) based on the wizard state. It reuses the existing `ScreenRecorder` class.

**Step 1: Create the capture step renderer**

The capture step must:
- Show a textarea with adaptive placeholder
- Show video/screenshot buttons based on `getCaptureOptions()`
- Show mic/camera toggles when video is selected
- Show recording controls (start, pause, stop, timer)
- Show preview after recording
- Show a "Continue" button

This is the most complex step. Create a ~200-line module that handles the textarea + recording controls + preview. Reuse `ScreenRecorder` from `../recorder/screen-recorder.ts`.

Key structure:
```typescript
export function renderCaptureStep(
  container: HTMLElement,
  state: WizardState,
  config: ShowdeskConfig,
  onComplete: (updates: Partial<WizardState>) => void,
  onBack: () => void,
): void { /* ... */ }
```

**Step 2: Build and verify**

**Step 3: Commit**

```bash
git add widget/src/ui/wizard/step-capture.ts
git commit -m "feat(widget): add capture step UI with adaptive tools"
```

---

### Task 4.4: Create contact/recap step UI

**Files:**
- Create: `widget/src/ui/wizard/step-contact.ts`

Two modes:
- **Identity known** → recap screen (user info, issue type, description preview, attachment info, tech context mention)
- **Anonymous** → name + email fields

```typescript
export function renderContactStep(
  container: HTMLElement,
  state: WizardState,
  hasIdentity: boolean,
  onComplete: (updates: Partial<WizardState>) => void,
  onBack: () => void,
): void { /* ... */ }
```

**Step 1: Create the module**

**Step 2: Build and verify**

**Step 3: Commit**

```bash
git add widget/src/ui/wizard/step-contact.ts
git commit -m "feat(widget): add contact/recap step with identity-aware display"
```

---

### Task 4.5: Create confirmation step UI

**Files:**
- Create: `widget/src/ui/wizard/step-confirmation.ts`

Simple screen: checkmark animation, ticket reference, close button.

```typescript
export function renderConfirmationStep(
  container: HTMLElement,
  ticketReference: string,
  onClose: () => void,
): void { /* ... */ }
```

**Step 1: Create the module**

**Step 2: Build and verify**

**Step 3: Commit**

```bash
git add widget/src/ui/wizard/step-confirmation.ts
git commit -m "feat(widget): add confirmation step with ticket reference"
```

---

### Task 4.6: Rewrite modal.ts as wizard orchestrator

**Files:**
- Modify: `widget/src/ui/modal.ts` (major rewrite)

Replace the current single-form modal with a wizard that orchestrates the steps.

The new `createModal()` function:
1. Creates the overlay + modal shell (header with step indicator, content area)
2. Initializes `WizardState` with pre-filled user info
3. Renders the qualification step
4. On each step completion, updates state and renders the next step
5. On the contact/recap step "Send", calls `submitTicket()` + optionally `uploadVideo()`
6. Shows confirmation on success

**Step 1: Rewrite modal.ts**

Keep the overlay/modal creation. Replace the form body with a `<div class="sd-wizard-content">` that each step renders into. The orchestration logic calls `renderQualificationStep`, `renderCaptureStep`, `renderContactStep`, `renderConfirmationStep` in sequence.

**Step 2: Update styles.ts**

Add CSS for:
- `.sd-wizard-step` (fade-in transition between steps)
- `.sd-issue-type-grid` (2-column grid)
- `.sd-issue-type-btn` (card-style buttons with icon + label)
- `.sd-followup-btn` (full-width option buttons)
- `.sd-back-btn` (subtle back link)
- `.sd-step-indicator` (dot progress: ● ○ ○)
- `.sd-recommended-badge` (small badge on recommended capture options)
- `.sd-recap-card` (summary card on contact step)

**Step 3: Build and test manually on widget demo page**

Run: `cd widget && npm run build`
Open: `http://localhost/widget-demo`
Test the full wizard flow manually.

**Step 4: Commit**

```bash
git add widget/src/ui/modal.ts widget/src/ui/styles.ts widget/src/ui/wizard/
git commit -m "feat(widget): rewrite modal as guided wizard with adaptive steps"
```

---

### Task 4.7: Send issue_type with ticket

**Files:**
- Modify: `widget/src/api/submit.ts`

In `submitTicket()`, add `issue_type` to the request body from the wizard state:

```typescript
const body = {
  ...data,
  issue_type: data.issue_type || "other",
  external_user_id: config.user?.id || "",
};
```

Update `TicketSubmission` type in `types.ts` to include `issue_type`.

**Step 1: Update types and submit**

**Step 2: Build**

**Step 3: Commit**

```bash
git add widget/src/api/submit.ts widget/src/types.ts
git commit -m "feat(widget): send issue_type with ticket submission"
```

---

## Batch 5 — Widget: Camera PiP (Canvas Compositing)

### Task 5.1: Create PiP compositor class

**Files:**
- Create: `widget/src/recorder/pip-compositor.ts`

This is the core Canvas compositing engine. It draws the screen + camera bubble on an offscreen canvas at ~30fps.

```typescript
// widget/src/recorder/pip-compositor.ts

export type BubblePosition = "top-left" | "top-right" | "bottom-left" | "bottom-right";
export type BubbleSize = "large" | "mini";

export interface PipCompositorOptions {
  screenStream: MediaStream;
  cameraStream: MediaStream;
  width: number;
  height: number;
}

export class PipCompositor {
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private screenVideo: HTMLVideoElement;
  private cameraVideo: HTMLVideoElement;
  private animationId: number | null = null;
  private _position: BubblePosition = "bottom-right";
  private _size: BubbleSize = "large";
  private _cameraEnabled = true;

  constructor(options: PipCompositorOptions) { /* ... */ }

  get stream(): MediaStream {
    return this.canvas.captureStream(30);
  }

  set position(pos: BubblePosition) { this._position = pos; }
  set size(s: BubbleSize) { this._size = s; }

  toggleCamera(): void { this._cameraEnabled = !this._cameraEnabled; }

  start(): void {
    this.screenVideo.srcObject = /* screenStream */;
    this.cameraVideo.srcObject = /* cameraStream */;
    this.screenVideo.play();
    this.cameraVideo.play();
    this.render();
  }

  stop(): void {
    if (this.animationId) cancelAnimationFrame(this.animationId);
    /* cleanup */
  }

  private render = (): void => {
    // 1. Draw screen full canvas
    this.ctx.drawImage(this.screenVideo, 0, 0, this.canvas.width, this.canvas.height);

    // 2. Draw camera bubble if enabled
    if (this._cameraEnabled) {
      const bubbleRadius = this._size === "large" ? 60 : 30;
      const margin = 16;
      const { x, y } = this.getBubbleCenter(bubbleRadius, margin);

      // Circular clip
      this.ctx.save();
      this.ctx.beginPath();
      this.ctx.arc(x, y, bubbleRadius, 0, Math.PI * 2);
      this.ctx.clip();
      this.ctx.drawImage(
        this.cameraVideo,
        x - bubbleRadius, y - bubbleRadius,
        bubbleRadius * 2, bubbleRadius * 2,
      );
      this.ctx.restore();

      // Border
      this.ctx.beginPath();
      this.ctx.arc(x, y, bubbleRadius, 0, Math.PI * 2);
      this.ctx.strokeStyle = "white";
      this.ctx.lineWidth = 3;
      this.ctx.stroke();
    }

    this.animationId = requestAnimationFrame(this.render);
  };

  private getBubbleCenter(radius: number, margin: number): { x: number; y: number } {
    const d = radius + margin;
    switch (this._position) {
      case "top-left": return { x: d, y: d };
      case "top-right": return { x: this.canvas.width - d, y: d };
      case "bottom-left": return { x: d, y: this.canvas.height - d };
      case "bottom-right": return { x: this.canvas.width - d, y: this.canvas.height - d };
    }
  }

  destroy(): void {
    this.stop();
    this.screenVideo.srcObject = null;
    this.cameraVideo.srcObject = null;
  }
}
```

**Step 1: Create the module with full implementation**

**Step 2: Build**

Run: `cd widget && npm run build`

**Step 3: Commit**

```bash
git add widget/src/recorder/pip-compositor.ts
git commit -m "feat(widget): add PiP canvas compositor for camera bubble overlay"
```

---

### Task 5.2: Integrate PiP into ScreenRecorder

**Files:**
- Modify: `widget/src/recorder/screen-recorder.ts`

When camera is enabled, instead of adding camera tracks directly to the MediaStream:
1. Create `PipCompositor` with screen + camera streams
2. Use `compositor.stream` (canvas capture) as the video source for MediaRecorder
3. Add audio track from mic separately

**Step 1: Modify the `start()` method**

Replace the current camera handling (lines 67-81) with PipCompositor integration:

```typescript
if (options.camera) {
  const cameraStream = await navigator.mediaDevices.getUserMedia({
    video: { width: { ideal: 320 }, height: { ideal: 240 }, facingMode: "user" },
  });
  this.streams.push(cameraStream);

  // Use PiP compositor instead of raw track
  this.compositor = new PipCompositor({
    screenStream: screenStream,
    cameraStream: cameraStream,
    width: screenStream.getVideoTracks()[0].getSettings().width || 1920,
    height: screenStream.getVideoTracks()[0].getSettings().height || 1080,
  });
  this.compositor.start();

  // Use compositor canvas stream for video
  tracks.length = 0; // Clear raw screen tracks
  tracks.push(...this.compositor.stream.getVideoTracks());

  // Re-add audio tracks
  if (audioTrack) tracks.push(audioTrack);
}
```

Update `cleanup()` to call `compositor.destroy()`.

**Step 2: Expose compositor for UI controls**

Add a getter:
```typescript
get pipCompositor(): PipCompositor | null {
  return this.compositor || null;
}
```

This lets the recording UI wire drag/click events to `compositor.position` and `compositor.size`.

**Step 3: Add fallback**

If `canvas.captureStream` is not available, fall back to current behavior (log a warning).

**Step 4: Build and test**

Run: `cd widget && npm run build`
Test on widget-demo page with camera enabled.

**Step 5: Commit**

```bash
git add widget/src/recorder/screen-recorder.ts widget/src/recorder/pip-compositor.ts
git commit -m "feat(widget): integrate PiP compositor into screen recorder"
```

---

### Task 5.3: Add draggable bubble overlay during recording

**Files:**
- Modify: `widget/src/ui/wizard/step-capture.ts`

During recording, show a small floating overlay on the page (outside the widget modal, which is hidden during recording) with:
- Camera bubble position indicator (4 corner buttons)
- Size toggle (large/mini)
- Recording timer + controls (pause, stop)

When user clicks a corner indicator, call `recorder.pipCompositor.position = "bottom-left"` etc.

**Step 1: Create recording overlay UI**

**Step 2: Wire events to compositor**

**Step 3: Build and test**

**Step 4: Commit**

```bash
git add widget/src/ui/wizard/step-capture.ts
git commit -m "feat(widget): add draggable camera bubble controls during recording"
```

---

## Batch 6 — Frontend: Enhanced Technical Context Display

### Task 6.1: Display console errors in TicketDetail

**Files:**
- Modify: `frontend/src/components/tickets/TicketDetail.tsx` (Technical Context section)

**Step 1: Add collapsible console errors panel**

In the Technical Context section (around line 377), after existing metadata display:

```tsx
{ticket.context_metadata?.console_errors?.length > 0 && (
  <CollapsibleSection
    title={`Console Errors (${ticket.context_metadata.console_errors.length})`}
    defaultOpen={true}
  >
    <div className="space-y-2 max-h-60 overflow-y-auto">
      {ticket.context_metadata.console_errors.map((entry, i) => (
        <div key={i} className="rounded bg-gray-50 p-2 text-xs font-mono">
          <span className={entry.level === "error" ? "text-red-600" : "text-orange-500"}>
            {entry.level === "error" ? "\u274C" : "\u26A0\uFE0F"} {entry.message}
          </span>
          {entry.source && (
            <div className="text-gray-400 mt-0.5">{entry.source}</div>
          )}
          <div className="text-gray-400 mt-0.5">{entry.timestamp}</div>
        </div>
      ))}
    </div>
  </CollapsibleSection>
)}
```

**Step 2: Add collapsible network errors panel**

```tsx
{ticket.context_metadata?.network_errors?.length > 0 && (
  <CollapsibleSection
    title={`Network Errors (${ticket.context_metadata.network_errors.length})`}
    defaultOpen={true}
  >
    <div className="space-y-2 max-h-60 overflow-y-auto">
      {ticket.context_metadata.network_errors.map((entry, i) => (
        <div key={i} className="rounded bg-gray-50 p-2 text-xs font-mono">
          <span className="text-red-600">
            \uD83D\uDD34 {entry.status} {entry.method} {entry.url}
          </span>
          <div className="text-gray-400 mt-0.5">
            Duration: {entry.duration_ms}ms \u00B7 {entry.timestamp}
          </div>
        </div>
      ))}
    </div>
  </CollapsibleSection>
)}
```

**Step 3: Create CollapsibleSection component (if not exists)**

Simple component with a toggle button and animated height.

**Step 4: Add issue_type badge near ticket title**

Show a small colored badge next to the ticket title indicating the issue type (Bug, Question, Suggestion, Other).

**Step 5: Update Ticket TypeScript type**

In `frontend/src/types/index.ts`, ensure `issue_type` and `external_user_id` are in the Ticket interface. Update `context_metadata` type to include `console_errors` and `network_errors` arrays.

**Step 6: Build and verify**

Run: `cd frontend && npm run build`

**Step 7: Commit**

```bash
git add frontend/src/components/tickets/TicketDetail.tsx frontend/src/types/index.ts
git commit -m "feat(frontend): display console/network errors and issue type in ticket detail"
```

---

## Batch 7 — Integration Testing & Polish

### Task 7.1: Update Playwright E2E tests

**Files:**
- Modify: `e2e/` or widget test files

Update existing E2E tests to work with the new wizard flow (the old form selectors will break). Add new tests:
- Test qualification step navigation
- Test wizard flow: bug → visible → capture → send
- Test wizard flow: question → capture → send (no video option)
- Test pre-filled identity skips contact step

### Task 7.2: Full regression test

Run all test suites:
- `docker compose exec backend pytest -v`
- `cd frontend && npm run test`
- `cd widget && npm run build` (no errors)
- Playwright E2E suite

### Task 7.3: Manual QA on widget-demo page

- Test all 4 issue types through the wizard
- Test camera PiP recording with bubble drag
- Test with user identity pre-filled
- Test anonymous flow (no identity)
- Verify console/network errors appear in agent ticket detail
- Test on Chrome, Firefox, Safari

---

## Summary

| Batch | Tasks | Scope |
|-------|-------|-------|
| 1 | 1.1 — 1.4 | Backend: `issue_type`, `external_user_id`, enriched context_metadata |
| 2 | 2.1 — 2.3 | Widget: Console + network error collectors from script load |
| 3 | 3.1 — 3.2 | Widget: User identity API + pre-fill + external_user_id |
| 4 | 4.1 — 4.7 | Widget: Guided wizard flow (qualification → capture → contact → confirm) |
| 5 | 5.1 — 5.3 | Widget: Camera PiP canvas compositor + draggable bubble |
| 6 | 6.1 | Frontend: Enhanced technical context display + issue type badge |
| 7 | 7.1 — 7.3 | Integration tests, regression, manual QA |

**Estimated tasks:** 20
**Estimated commits:** ~15-18
