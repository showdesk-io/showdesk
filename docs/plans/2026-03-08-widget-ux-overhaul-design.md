# Widget UX Overhaul — Design Document

> Date: 2026-03-08
> Status: Validated
> Phase: 2 (Widget UX Overhaul)

---

## Goal

Transform the widget from a simple form into a guided, context-rich support experience that captures the right information with minimal user effort.

Three pillars:
1. **Guided wizard flow** — adaptive steps based on issue type
2. **Camera Picture-in-Picture** — Loom-style webcam bubble on screen recording
3. **Automatic technical context** — silent capture of console/network errors from script load

---

## 1. Widget Initialization

### Script load (silent, no UI)

The widget script begins capturing technical context immediately on load, before any user interaction.

```javascript
// Host app integration
<script src="https://cdn.showdesk.io/widget.js" data-token="org_xxx"></script>

// Optional: pass authenticated user identity
<script>
  Showdesk.init({
    user: {
      id: "usr_123",        // ID in host application
      name: "Jean Dupont",
      email: "jean@acme.com"
    }
  });
</script>
```

**Hooks installed at script load:**

| Hook | Method | Buffer |
|------|--------|--------|
| JS errors | `window.addEventListener("error", ...)` | Last 50 |
| Console errors/warnings | Monkey-patch `console.error`, `console.warn` | Last 50 |
| Network errors (4xx/5xx) | Monkey-patch `fetch` + `XMLHttpRequest` | Last 50 |
| Browser metadata | `navigator.userAgent`, `screen`, `location.href` | Snapshot at submit |

All data stored in memory only (no localStorage, no network requests). Buffer attached to ticket at submit time.

### User identity

When `Showdesk.init({ user })` is called:
- Contact fields are pre-filled (name, email)
- Contact step is skipped entirely if all fields present
- `external_user_id` is stored on the ticket for cross-referencing

---

## 2. Guided Wizard Flow

### Phase 1 — Qualification (1-2 questions)

**Question 1: Issue type**

| Choice | Icon |
|--------|------|
| Bug / problem | Bug icon |
| Can't find / don't understand | Question icon |
| Suggestion | Lightbulb icon |
| Other | Mail icon |

**Question 2 (conditional):**

| Type | Follow-up | Purpose |
|------|-----------|---------|
| Bug | "Is the problem visible on screen?" (yes/no) | Determines if video is recommended |
| Question | None | Skip to capture |
| Suggestion | None | Skip to capture |
| Other | None | Skip to capture |

### Phase 2 — Capture (adapted to context)

Available tools per issue type:

| Type | Textarea | Video | Screenshot | Micro | Camera |
|------|----------|-------|------------|-------|--------|
| Bug (visible) | Required | **Recommended** | Available | Yes | Yes |
| Bug (not visible) | Required | Available | No | Yes (mic only) | No |
| Question | Required | No | Available | No | No |
| Suggestion | Required | Available | Available | Yes | Yes |
| Other | Required | Available | Available | Yes | Yes |

"Recommended" means the video option is visually highlighted (badge/border) but not required.

**Textarea placeholder adapts to type:**
- Bug: "What do you see? What did you expect?"
- Question: "What are you trying to do?"
- Suggestion: "What would you like to see improved?"
- Other: "How can we help?"

### Phase 3 — Contact & Send

**If user identity is known:** Skip contact fields. Show a recap screen with:
- User identity (name, email)
- Issue type
- Description preview
- Attached capture (video/screenshot) with metadata
- Discreet mention of technical context ("3 console errors, 1 network error")
- "Edit" and "Send" buttons

**If anonymous:** Show name + email fields, then send.

### Confirmation screen

- Checkmark animation
- Ticket reference (e.g. SD-0042)
- "We'll get back to you shortly."
- Close button

---

## 3. Camera Picture-in-Picture

### Architecture

Canvas compositing in the browser. Screen + camera drawn on an offscreen canvas, recorded as a single stream.

```
getUserMedia (camera 320x240)  --+
                                 +--> Canvas (offscreen) --> captureStream(30) --> MediaRecorder --> WebM
getDisplayMedia (screen)  -------+          ^
                                            |
                                  requestAnimationFrame loop
                                  draws screen + circular camera bubble
```

### Render loop (per frame, ~30fps)

1. `drawImage()` screen video onto full canvas
2. `arc()` + `clip()` to create circular mask
3. `drawImage()` camera video into the circle
4. `stroke()` white border (3px) around circle

### Camera bubble UX

**Size:** 120px diameter (large), 60px (mini)
**Default position:** Bottom-right corner, 16px margin
**Snap positions:** 4 corners

| Interaction | Behavior |
|------------|----------|
| Drag | Bubble snaps to nearest corner on release |
| Click | Toggle large (120px) / mini (60px) |
| Double-click | Disable camera temporarily (grey dot, "cam off") |

### Recording controls overlay

Floating bar at bottom center during recording:

```
    [red dot] 00:34     [pause]     [Stop]
```

- Pulsing red dot + timer
- Pause/resume button
- "Stop" ends recording, returns to widget with preview

### Fallback

If `canvas.captureStream()` is not supported, fall back to current behavior (camera as separate video track). Better than nothing.

### Performance

- `requestAnimationFrame` at 30fps: ~5-10% CPU. Acceptable for short recordings (few minutes max).
- Canvas destroyed immediately after recording ends.

---

## 4. Automatic Technical Context

### Capture strategy

All hooks installed at **script load time** (not when widget opens). This ensures errors that occurred before the user decided to report are captured.

### Data format

Stored in the existing `technical_context` JSONField on Ticket:

```json
{
  "url": "https://app.acme.com/settings",
  "browser": "Chrome 128",
  "os": "macOS 15.2",
  "resolution": "2560x1440",
  "console_errors": [
    {
      "level": "error",
      "message": "TypeError: Cannot read property 'id' of undefined",
      "source": "Settings.tsx:142",
      "timestamp": "2026-03-08T10:32:15.123Z"
    }
  ],
  "network_errors": [
    {
      "method": "POST",
      "url": "/api/v1/settings/",
      "status": 500,
      "duration_ms": 234,
      "timestamp": "2026-03-08T10:32:14.456Z"
    }
  ]
}
```

### Privacy

- Network error capture stores URL and status only, never request/response bodies
- Console messages are truncated at 500 characters
- No PII scrubbing needed at this stage (errors rarely contain PII)
- Buffer is memory-only, never persisted to localStorage

### Agent-side display

In ticket detail, the "Technical Context" panel (right sidebar) is enriched:

- **Console Errors (N)** — collapsible section, open by default if errors present
- **Network Errors (N)** — collapsible section, open by default if errors present
- Chronological order (most recent first)
- Error level indicated by color (red = error, orange = warning)
- Timestamp relative to ticket submission
- Sections hidden entirely if no errors (no "0 errors" noise)

---

## 5. Data Model Changes

### Ticket model

**New field: `issue_type`**

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

**New field: `external_user_id`**

```python
external_user_id = models.CharField(
    max_length=255,
    blank=True,
    default="",
    db_index=True,
    help_text="User ID from the host application, passed via widget init.",
)
```

**Existing field: `technical_context` (JSONField)**

No migration needed. The JSON structure is extended with `console_errors` and `network_errors` arrays. Backend accepts any JSON.

### VideoRecording model

No changes. Camera PiP is composited client-side into a single WebM. Existing `has_camera` and `recording_type` fields are sufficient.

---

## 6. Not in scope (roadmap items)

| Feature | Priority | Phase |
|---------|----------|-------|
| Ticket history in widget (view previous tickets + replies) | P2 | 2 |
| Screenshot + annotation (Marker.io-style) | P2 | 2 |
| Multi-attachments per ticket | P2 | 2 |
| Session replay (lightweight DOM event capture) | P3 | 2 |
| Video timeline markers | P3 | 2 |
| AI first-responder in widget | — | 5 |
