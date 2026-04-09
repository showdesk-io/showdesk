/**
 * Widget CSS styles injected into the host page.
 *
 * All styles are scoped under #showdesk-widget-container to avoid
 * conflicts with the host page's styles. The widget must work in
 * any environment without breaking existing layouts.
 */

const HEX_COLOR_RE = /^#[0-9a-fA-F]{6}$/;
const DEFAULT_PRIMARY = "#6366f1";

export function injectStyles(primaryColor: string): void {
  if (document.getElementById("showdesk-widget-styles")) {
    return;
  }

  const safeColor = HEX_COLOR_RE.test(primaryColor) ? primaryColor : DEFAULT_PRIMARY;

  const style = document.createElement("style");
  style.id = "showdesk-widget-styles";
  style.textContent = `
    #showdesk-widget-container {
      --sd-primary: ${safeColor};
      --sd-primary-hover: ${adjustBrightness(safeColor, -15)};
      --sd-text: #1f2937;
      --sd-text-light: #6b7280;
      --sd-bg: #ffffff;
      --sd-border: #e5e7eb;
      --sd-radius: 12px;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      font-size: 14px;
      line-height: 1.5;
      color: var(--sd-text);
      z-index: 2147483647;
    }

    .sd-button {
      position: fixed;
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 12px 20px;
      background: var(--sd-primary);
      color: white;
      border: none;
      border-radius: 50px;
      cursor: pointer;
      font-size: 14px;
      font-weight: 600;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
      transition: all 0.2s ease;
      z-index: 2147483647;
    }

    .sd-button:hover {
      background: var(--sd-primary-hover);
      transform: translateY(-1px);
      box-shadow: 0 6px 16px rgba(0, 0, 0, 0.2);
    }

    .sd-button.bottom-right {
      bottom: 24px;
      right: 24px;
    }

    .sd-button.bottom-left {
      bottom: 24px;
      left: 24px;
    }

    .sd-overlay {
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.4);
      z-index: 2147483646;
      animation: sd-fadeIn 0.2s ease;
    }

    .sd-modal {
      position: fixed;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      width: 90%;
      max-width: 520px;
      max-height: 90vh;
      background: var(--sd-bg);
      border-radius: var(--sd-radius);
      box-shadow: 0 20px 60px rgba(0, 0, 0, 0.2);
      overflow: auto;
      z-index: 2147483647;
      animation: sd-slideIn 0.3s ease;
    }

    .sd-modal-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 20px 24px 12px;
    }

    .sd-modal-header h2 {
      font-size: 18px;
      font-weight: 700;
      color: var(--sd-text);
      margin: 0;
    }

    .sd-modal-close {
      background: none;
      border: none;
      font-size: 24px;
      color: var(--sd-text-light);
      cursor: pointer;
      padding: 4px;
      line-height: 1;
    }

    .sd-modal-body {
      padding: 12px 24px 24px;
    }

    .sd-field {
      margin-bottom: 16px;
    }

    .sd-field label {
      display: block;
      font-size: 13px;
      font-weight: 500;
      color: var(--sd-text);
      margin-bottom: 4px;
    }

    .sd-field input,
    .sd-field textarea {
      width: 100%;
      padding: 10px 12px;
      border: 1px solid var(--sd-border);
      border-radius: 8px;
      font-size: 14px;
      color: var(--sd-text);
      background: var(--sd-bg);
      outline: none;
      transition: border-color 0.15s;
      box-sizing: border-box;
    }

    .sd-field input:focus,
    .sd-field textarea:focus {
      border-color: var(--sd-primary);
    }

    .sd-field textarea {
      resize: vertical;
      min-height: 80px;
    }

    .sd-recorder-controls {
      display: flex;
      gap: 8px;
      margin-bottom: 16px;
      flex-wrap: wrap;
    }

    .sd-recorder-btn {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 8px 14px;
      border: 1px solid var(--sd-border);
      border-radius: 8px;
      background: var(--sd-bg);
      color: var(--sd-text);
      cursor: pointer;
      font-size: 13px;
      transition: all 0.15s;
    }

    .sd-recorder-btn:hover {
      border-color: var(--sd-primary);
      color: var(--sd-primary);
    }

    .sd-recorder-btn.active {
      background: var(--sd-primary);
      color: white;
      border-color: var(--sd-primary);
    }

    .sd-recorder-btn.recording {
      background: #ef4444;
      color: white;
      border-color: #ef4444;
      animation: sd-pulse 2s infinite;
    }

    .sd-recording-indicator {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 12px;
      background: #fef2f2;
      border: 1px solid #fecaca;
      border-radius: 8px;
      margin-bottom: 16px;
      font-size: 13px;
      color: #991b1b;
    }

    .sd-recording-dot {
      width: 10px;
      height: 10px;
      background: #ef4444;
      border-radius: 50%;
      animation: sd-pulse 1s infinite;
    }

    .sd-submit-btn {
      width: 100%;
      padding: 12px;
      background: var(--sd-primary);
      color: white;
      border: none;
      border-radius: 8px;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.15s;
    }

    .sd-submit-btn:hover {
      background: var(--sd-primary-hover);
    }

    .sd-submit-btn:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }

    .sd-success {
      text-align: center;
      padding: 32px 24px;
    }

    .sd-success h3 {
      font-size: 18px;
      font-weight: 700;
      color: var(--sd-text);
      margin: 16px 0 8px;
    }

    .sd-success p {
      color: var(--sd-text-light);
      margin: 0;
    }

    .sd-file-input {
      display: none;
    }

    .sd-error {
      padding: 10px 14px;
      background: #fef2f2;
      border: 1px solid #fecaca;
      border-radius: 8px;
      color: #991b1b;
      font-size: 13px;
      margin-bottom: 12px;
    }

    .sd-wizard-step {
      padding: 4px 0;
      animation: sd-wizardFadeIn 0.25s ease;
    }

    .sd-wizard-title {
      font-size: 16px;
      font-weight: 700;
      color: var(--sd-text);
      margin: 0 0 16px;
    }

    .sd-wizard-actions {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-top: 16px;
    }

    .sd-issue-type-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }

    .sd-issue-type-btn {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 6px;
      padding: 16px 12px;
      border: 1px solid var(--sd-border);
      border-radius: var(--sd-radius);
      background: var(--sd-bg);
      cursor: pointer;
      font-size: 13px;
      color: var(--sd-text);
      transition: all 0.15s;
    }

    .sd-issue-type-btn:hover {
      border-color: var(--sd-primary);
      color: var(--sd-primary);
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
    }

    .sd-issue-type-icon {
      font-size: 24px;
    }

    .sd-followup-btn {
      display: block;
      width: 100%;
      padding: 14px 16px;
      border: 1px solid var(--sd-border);
      border-radius: var(--sd-radius);
      background: var(--sd-bg);
      cursor: pointer;
      font-size: 14px;
      color: var(--sd-text);
      text-align: left;
      transition: all 0.15s;
      margin-bottom: 8px;
    }

    .sd-followup-btn:hover {
      border-color: var(--sd-primary);
      color: var(--sd-primary);
    }

    .sd-back-btn {
      background: none;
      border: none;
      color: var(--sd-text-light);
      cursor: pointer;
      font-size: 13px;
      padding: 6px 4px;
      transition: color 0.15s;
    }

    .sd-back-btn:hover {
      color: var(--sd-text);
    }

    .sd-step-dots {
      display: flex;
      align-items: center;
      gap: 6px;
    }

    .sd-step-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--sd-border);
      transition: background 0.2s;
    }

    .sd-step-dot.sd-step-active {
      background: var(--sd-primary);
    }

    .sd-recommended-badge {
      font-size: 10px;
      font-weight: 600;
      color: var(--sd-primary);
      background: color-mix(in srgb, var(--sd-primary) 10%, transparent);
      padding: 2px 6px;
      border-radius: 4px;
    }

    .sd-recap-card {
      border: 1px solid var(--sd-border);
      border-radius: var(--sd-radius);
      padding: 16px;
      margin-bottom: 8px;
    }

    .sd-recap-row {
      font-size: 13px;
      color: var(--sd-text);
      margin-bottom: 8px;
    }

    .sd-recap-row:last-child {
      margin-bottom: 0;
    }

    .sd-recap-description {
      font-size: 13px;
      color: var(--sd-text-light);
      margin: 8px 0;
      line-height: 1.5;
    }

    .sd-recap-context {
      font-size: 11px;
      color: var(--sd-text-light);
      font-style: italic;
    }

    .sd-issue-badge {
      display: inline-block;
      font-size: 11px;
      font-weight: 600;
      text-transform: capitalize;
      color: var(--sd-primary);
      background: color-mix(in srgb, var(--sd-primary) 10%, transparent);
      padding: 2px 8px;
      border-radius: 4px;
    }

    .sd-recording-panel {
      padding: 12px;
      border: 1px solid var(--sd-border);
      border-radius: var(--sd-radius);
      margin-bottom: 12px;
    }

    .sd-recording-preview {
      margin-bottom: 12px;
    }

    .sd-loading-spinner {
      width: 36px;
      height: 36px;
      border: 3px solid var(--sd-border);
      border-top-color: var(--sd-primary);
      border-radius: 50%;
      animation: sd-spin 0.7s linear infinite;
      margin: 0 auto;
    }

    @keyframes sd-spin {
      to { transform: rotate(360deg); }
    }

    @keyframes sd-fadeIn {
      from { opacity: 0; }
      to { opacity: 1; }
    }

    @keyframes sd-wizardFadeIn {
      from { opacity: 0; transform: translateY(6px); }
      to { opacity: 1; transform: translateY(0); }
    }

    @keyframes sd-slideIn {
      from { opacity: 0; transform: translate(-50%, -48%); }
      to { opacity: 1; transform: translate(-50%, -50%); }
    }

    @keyframes sd-pulse {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.5; }
    }

    /* ---------------------------------------------------------------- */
    /* Messaging panel                                                   */
    /* ---------------------------------------------------------------- */

    .sd-panel {
      position: fixed;
      width: 380px;
      height: 600px;
      max-height: 80vh;
      background: var(--sd-bg);
      border-radius: var(--sd-radius);
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.18);
      display: flex;
      flex-direction: column;
      overflow: hidden;
      z-index: 2147483647;
      animation: sd-panelSlideUp 0.3s ease;
    }

    .sd-panel.sd-panel-bottom-right {
      bottom: 80px;
      right: 24px;
    }

    .sd-panel.sd-panel-bottom-left {
      bottom: 80px;
      left: 24px;
    }

    @media (max-width: 480px) {
      .sd-panel {
        width: calc(100% - 16px);
        height: calc(100vh - 100px);
        max-height: none;
        right: 8px !important;
        left: 8px !important;
        bottom: 70px;
        border-radius: 16px 16px 0 0;
      }
    }

    @keyframes sd-panelSlideUp {
      from { opacity: 0; transform: translateY(20px); }
      to { opacity: 1; transform: translateY(0); }
    }

    .sd-panel-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 16px 20px 12px;
      background: var(--sd-primary);
      color: white;
    }

    .sd-panel-greeting {
      font-size: 16px;
      font-weight: 600;
    }

    .sd-panel-close {
      background: none;
      border: none;
      color: rgba(255, 255, 255, 0.8);
      font-size: 24px;
      cursor: pointer;
      padding: 0;
      line-height: 1;
    }

    .sd-panel-close:hover {
      color: white;
    }

    /* Tab bar */
    .sd-tab-bar {
      display: flex;
      border-bottom: 1px solid var(--sd-border);
      background: var(--sd-bg);
    }

    .sd-tab {
      flex: 1;
      padding: 10px 12px;
      border: none;
      background: none;
      font-size: 13px;
      font-weight: 500;
      color: var(--sd-text-light);
      cursor: pointer;
      border-bottom: 2px solid transparent;
      transition: all 0.15s;
    }

    .sd-tab:hover {
      color: var(--sd-text);
    }

    .sd-tab-active {
      color: var(--sd-primary);
      border-bottom-color: var(--sd-primary);
    }

    /* Content area */
    .sd-panel-content {
      flex: 1;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }

    /* Message list */
    .sd-message-list {
      flex: 1;
      overflow-y: auto;
      padding: 12px 16px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    /* Empty state */
    .sd-empty-state {
      flex: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      text-align: center;
      gap: 12px;
      padding: 24px 16px 8px;
      animation: sd-fadeIn 0.3s ease;
    }

    .sd-empty-icon {
      opacity: 0.7;
    }

    .sd-empty-title {
      font-size: 16px;
      font-weight: 600;
      color: var(--sd-text);
      margin: 0;
    }

    .sd-empty-chips {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      justify-content: center;
    }

    .sd-empty-chip {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 4px 10px;
      border-radius: 12px;
      background: #f1f5f9;
      color: var(--sd-text-light);
      font-size: 12px;
      font-weight: 500;
    }

    .sd-empty-hint {
      font-size: 13px;
      color: var(--sd-text-light);
      margin: 4px 0 0;
      line-height: 1.5;
    }

    .sd-empty-hint strong {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 20px;
      height: 20px;
      border-radius: 50%;
      border: 1px solid var(--sd-border);
      font-size: 14px;
      font-weight: 600;
      color: var(--sd-text);
      vertical-align: middle;
    }

    .sd-empty-arrow {
      animation: sd-bounce 2s ease-in-out infinite;
    }

    @keyframes sd-bounce {
      0%, 100% { transform: translateY(0); }
      50% { transform: translateY(4px); }
    }

    /* Message bubbles */
    .sd-msg {
      display: flex;
      flex-direction: column;
      max-width: 85%;
    }

    .sd-msg-user {
      align-self: flex-end;
    }

    .sd-msg-agent {
      align-self: flex-start;
    }

    .sd-msg-system {
      align-self: center;
      max-width: 100%;
    }

    .sd-msg-bubble {
      padding: 10px 14px;
      border-radius: 16px;
      font-size: 14px;
      line-height: 1.4;
      word-wrap: break-word;
    }

    .sd-msg-user .sd-msg-bubble {
      background: var(--sd-primary);
      color: white;
      border-bottom-right-radius: 4px;
      position: relative;
    }

    .sd-msg-agent .sd-msg-bubble {
      background: #f3f4f6;
      color: var(--sd-text);
      border-bottom-left-radius: 4px;
    }

    .sd-msg-system-text {
      font-size: 12px;
      color: var(--sd-text-light);
      text-align: center;
      padding: 4px 12px;
    }

    .sd-msg-time {
      font-size: 11px;
      color: var(--sd-text-light);
      margin-top: 2px;
      padding: 0 4px;
    }

    .sd-msg-user .sd-msg-time {
      text-align: right;
    }

    .sd-msg-delete {
      display: none;
      position: absolute;
      top: 4px;
      left: -28px;
      width: 22px;
      height: 22px;
      border-radius: 50%;
      border: none;
      background: #f1f5f9;
      color: #94a3b8;
      cursor: pointer;
      align-items: center;
      justify-content: center;
      font-size: 12px;
      transition: all 0.15s;
      padding: 0;
    }

    .sd-msg-delete:hover {
      background: #fee2e2;
      color: #ef4444;
    }

    .sd-msg-user:hover .sd-msg-delete {
      display: flex;
    }

    .sd-msg-status {
      display: block;
      font-size: 11px;
      margin-top: 4px;
      opacity: 0.8;
    }

    .sd-msg-status-failed {
      color: #fca5a5;
    }

    /* Media in messages */
    .sd-msg-image img {
      max-width: 100%;
      border-radius: 8px;
      cursor: pointer;
      display: block;
    }

    .sd-msg-caption {
      margin-top: 6px;
      font-size: 13px;
    }

    .sd-msg-audio {
      min-width: 220px;
    }
    .sd-msg-audio audio {
      width: 100%;
      height: 36px;
    }

    .sd-msg-video video {
      max-width: 100%;
      border-radius: 8px;
      display: block;
    }

    /* Input bar */
    .sd-input-bar {
      border-top: 1px solid var(--sd-border);
      background: var(--sd-bg);
      padding: 8px 12px;
    }

    .sd-input-row {
      display: flex;
      align-items: flex-end;
      gap: 8px;
    }

    .sd-input-attach-wrapper {
      position: relative;
    }

    .sd-input-attach {
      width: 36px;
      height: 36px;
      border-radius: 50%;
      border: 1px solid var(--sd-border);
      background: var(--sd-bg);
      font-size: 20px;
      color: var(--sd-text-light);
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: all 0.15s;
      flex-shrink: 0;
    }

    .sd-input-attach:hover {
      border-color: var(--sd-primary);
      color: var(--sd-primary);
    }

    .sd-input-textarea {
      flex: 1;
      border: 1px solid var(--sd-border);
      border-radius: 20px;
      padding: 8px 14px;
      font-size: 14px;
      color: var(--sd-text);
      background: var(--sd-bg);
      outline: none;
      resize: none;
      max-height: 80px;
      overflow-y: auto;
      font-family: inherit;
      line-height: 1.4;
    }

    .sd-input-textarea:focus {
      border-color: var(--sd-primary);
    }

    .sd-input-send {
      width: 36px;
      height: 36px;
      border-radius: 50%;
      border: none;
      background: var(--sd-primary);
      color: white;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: background 0.15s;
      flex-shrink: 0;
    }

    .sd-input-send:hover {
      background: var(--sd-primary-hover);
    }

    /* Attachment menu */
    .sd-attach-menu {
      background: var(--sd-bg);
      border: 1px solid var(--sd-border);
      border-radius: 12px;
      box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
      overflow: hidden;
      min-width: 160px;
      z-index: 10;
    }

    .sd-attach-menu-item {
      display: flex;
      align-items: center;
      gap: 10px;
      width: 100%;
      padding: 10px 16px;
      border: none;
      background: none;
      font-size: 14px;
      color: var(--sd-text);
      cursor: pointer;
      text-align: left;
    }

    .sd-attach-menu-item:hover {
      background: #f3f4f6;
    }

    .sd-attach-icon {
      font-size: 18px;
    }

    /* Recording inline indicator */
    .sd-recording-inline {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 8px 12px;
      background: #fef2f2;
      border-radius: 20px;
    }

    .sd-recording-timer {
      font-size: 14px;
      font-weight: 600;
      color: #991b1b;
      font-variant-numeric: tabular-nums;
    }

    .sd-recording-stop {
      margin-left: auto;
      padding: 4px 12px;
      background: #ef4444;
      color: white;
      border: none;
      border-radius: 12px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
    }

    /* Screenshot suggestion */
    .sd-screenshot-suggestion {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 10px 12px;
      background: #f0fdf4;
      border: 1px solid #bbf7d0;
      border-radius: 12px;
    }

    .sd-screenshot-preview img {
      width: 48px;
      height: 36px;
      object-fit: cover;
      border-radius: 4px;
      border: 1px solid var(--sd-border);
    }

    .sd-screenshot-text {
      flex: 1;
      font-size: 13px;
      color: var(--sd-text);
    }

    .sd-screenshot-actions {
      display: flex;
      gap: 6px;
    }

    /* Contact nudge */
    .sd-contact-nudge {
      padding: 10px 14px;
      background: #eff6ff;
      border: 1px solid #bfdbfe;
      border-radius: 12px;
    }

    .sd-nudge-text {
      font-size: 13px;
      color: #1e40af;
      margin-bottom: 8px;
    }

    .sd-nudge-form {
      flex-direction: column;
      gap: 6px;
    }

    .sd-nudge-actions {
      display: flex;
      gap: 6px;
    }

    .sd-input {
      width: 100%;
      padding: 6px 10px;
      border: 1px solid var(--sd-border);
      border-radius: 6px;
      font-size: 13px;
      color: var(--sd-text);
      outline: none;
      box-sizing: border-box;
    }

    .sd-input:focus {
      border-color: var(--sd-primary);
    }

    /* Small buttons */
    .sd-btn-small {
      padding: 4px 12px;
      font-size: 12px;
      font-weight: 600;
      border-radius: 6px;
      border: none;
      cursor: pointer;
      transition: all 0.15s;
    }

    .sd-btn-primary {
      background: var(--sd-primary);
      color: white;
    }

    .sd-btn-primary:hover {
      background: var(--sd-primary-hover);
    }

    .sd-btn-secondary {
      background: var(--sd-border);
      color: var(--sd-text);
    }

    .sd-btn-link {
      background: none;
      color: var(--sd-text-light);
      text-decoration: underline;
    }

    /* History view */
    .sd-history-view {
      flex: 1;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }

    .sd-btn-new-conversation {
      margin: 12px 16px;
      padding: 10px;
      border: 1px dashed var(--sd-border);
      border-radius: 8px;
      background: none;
      color: var(--sd-primary);
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.15s;
    }

    .sd-btn-new-conversation:hover {
      border-color: var(--sd-primary);
      background: color-mix(in srgb, var(--sd-primary) 5%, transparent);
    }

    .sd-history-list {
      flex: 1;
      overflow-y: auto;
      padding: 0 16px 16px;
    }

    .sd-history-empty, .sd-history-loading {
      text-align: center;
      color: var(--sd-text-light);
      font-size: 13px;
      padding: 32px 16px;
    }

    .sd-history-item {
      padding: 12px;
      border: 1px solid var(--sd-border);
      border-radius: 8px;
      cursor: pointer;
      margin-bottom: 8px;
      transition: all 0.15s;
    }

    .sd-history-item:hover {
      border-color: var(--sd-primary);
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
    }

    .sd-history-item-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 4px;
    }

    .sd-history-item-title {
      font-size: 14px;
      font-weight: 600;
      color: var(--sd-text);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      flex: 1;
    }

    .sd-status-badge {
      font-size: 10px;
      font-weight: 600;
      text-transform: uppercase;
      padding: 2px 6px;
      border-radius: 4px;
      white-space: nowrap;
    }

    .sd-status-open { background: #dbeafe; color: #1e40af; }
    .sd-status-in_progress { background: #fef3c7; color: #92400e; }
    .sd-status-waiting { background: #e5e7eb; color: #374151; }
    .sd-status-resolved { background: #d1fae5; color: #065f46; }
    .sd-status-closed { background: #f3f4f6; color: #6b7280; }

    .sd-history-item-preview {
      font-size: 13px;
      color: var(--sd-text-light);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .sd-history-item-meta {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-top: 4px;
      font-size: 11px;
      color: var(--sd-text-light);
    }

    .sd-unread-badge {
      background: var(--sd-primary);
      color: white;
      font-size: 10px;
      font-weight: 700;
      min-width: 18px;
      height: 18px;
      border-radius: 9px;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 0 5px;
    }

    /* FAB unread badge */
    .sd-fab-badge {
      position: absolute;
      top: -4px;
      right: -4px;
      background: #ef4444;
      color: white;
      font-size: 10px;
      font-weight: 700;
      min-width: 18px;
      height: 18px;
      border-radius: 9px;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 0 5px;
    }

    /* ---------------------------------------------------------------- */
    /* FAB — Recording controller mode                                   */
    /* ---------------------------------------------------------------- */

    .sd-button-recording {
      background: #1f2937 !important;
      gap: 10px;
      padding: 10px 16px !important;
      cursor: default !important;
    }

    .sd-button-recording:hover {
      transform: none !important;
    }

    .sd-rec-dot {
      width: 10px;
      height: 10px;
      background: #ef4444;
      border-radius: 50%;
      animation: sd-pulse 1s infinite;
      flex-shrink: 0;
    }

    .sd-rec-dot-waiting {
      background: #f59e0b;
      animation: sd-pulse 1.5s ease-in-out infinite;
    }

    .sd-rec-dot-uploading {
      background: #3b82f6;
      animation: sd-pulse 1s ease-in-out infinite;
    }

    .sd-rec-timer {
      font-size: 14px;
      font-weight: 600;
      font-variant-numeric: tabular-nums;
      color: white;
      min-width: 36px;
    }

    .sd-rec-mic-wrapper {
      display: flex;
      align-items: center;
      background: rgba(255, 255, 255, 0.15);
      border-radius: 16px;
      overflow: hidden;
    }

    .sd-rec-mic,
    .sd-rec-mic-select,
    .sd-rec-stop {
      display: flex;
      align-items: center;
      justify-content: center;
      border: none;
      cursor: pointer;
      transition: background 0.15s;
      flex-shrink: 0;
    }

    .sd-rec-mic {
      width: 32px;
      height: 32px;
      border-radius: 50%;
      background: transparent;
      color: white;
      font-size: 16px;
    }

    .sd-rec-mic:hover {
      background: rgba(255, 255, 255, 0.15);
    }

    .sd-rec-mic-select {
      width: 20px;
      height: 32px;
      background: transparent;
      color: rgba(255, 255, 255, 0.6);
      font-size: 10px;
      padding: 0;
      border-left: 1px solid rgba(255, 255, 255, 0.15);
    }

    .sd-rec-mic-select:hover {
      color: white;
      background: rgba(255, 255, 255, 0.15);
    }

    .sd-rec-stop {
      width: 32px;
      height: 32px;
      border-radius: 50%;
      background: #ef4444;
      color: white;
      font-size: 16px;
    }

    .sd-rec-stop:hover {
      background: #dc2626;
    }

    /* Mic selector dropdown */
    .sd-mic-selector {
      background: #1f2937;
      border: 1px solid rgba(255, 255, 255, 0.15);
      border-radius: 8px;
      box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
      overflow: hidden;
      z-index: 10;
    }

    .sd-mic-selector-item {
      display: block;
      width: 100%;
      padding: 8px 12px;
      border: none;
      background: none;
      color: white;
      font-size: 12px;
      text-align: left;
      cursor: pointer;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .sd-mic-selector-item:hover {
      background: rgba(255, 255, 255, 0.1);
    }
    .sd-mic-selector-active {
      background: rgba(255, 255, 255, 0.15);
      font-weight: 600;
    }
    .sd-mic-selector-active::before {
      content: "✓ ";
    }

    /* ---------------------------------------------------------------- */
    /* Video expand button                                               */
    /* ---------------------------------------------------------------- */

    .sd-msg-video {
      position: relative;
    }

    .sd-msg-video-expand {
      position: absolute;
      top: 6px;
      right: 6px;
      width: 28px;
      height: 28px;
      background: rgba(0, 0, 0, 0.5);
      color: white;
      border-radius: 6px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 16px;
      cursor: pointer;
      opacity: 0;
      transition: opacity 0.15s;
    }

    .sd-msg-video:hover .sd-msg-video-expand {
      opacity: 1;
    }

    .sd-msg-file {
      padding: 4px 0;
    }
    .sd-msg-file-link {
      display: flex;
      align-items: center;
      gap: 8px;
      color: inherit;
      text-decoration: none;
      padding: 6px 4px;
      border-radius: 6px;
      transition: background 0.15s;
    }
    .sd-msg-file-link:hover {
      background: rgba(0, 0, 0, 0.05);
    }
    .sd-msg-file-icon {
      font-size: 20px;
      flex-shrink: 0;
    }
    .sd-msg-file-name {
      font-size: 13px;
      word-break: break-all;
    }

    /* ---------------------------------------------------------------- */
    /* Media lightbox                                                     */
    /* ---------------------------------------------------------------- */

    .sd-lightbox-overlay {
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.75);
      z-index: 2147483647;
      display: flex;
      align-items: center;
      justify-content: center;
      animation: sd-fadeIn 0.2s ease;
    }

    .sd-lightbox-container {
      position: relative;
      width: 90%;
      max-width: 900px;
      max-height: 90vh;
      display: flex;
      flex-direction: column;
      align-items: center;
    }

    .sd-lightbox-close {
      position: absolute;
      top: -40px;
      right: 0;
      background: none;
      border: none;
      color: white;
      font-size: 32px;
      cursor: pointer;
      line-height: 1;
      padding: 4px;
      opacity: 0.8;
      transition: opacity 0.15s;
    }

    .sd-lightbox-close:hover {
      opacity: 1;
    }

    .sd-lightbox-media {
      width: 100%;
      display: flex;
      align-items: center;
      justify-content: center;
    }

    .sd-lightbox-media img {
      max-width: 100%;
      max-height: 85vh;
      border-radius: 8px;
      object-fit: contain;
    }

    .sd-lightbox-media video {
      max-width: 100%;
      max-height: 85vh;
      border-radius: 8px;
    }

    .sd-lightbox-audio-wrapper {
      background: #1f2937;
      border-radius: 16px;
      padding: 32px 48px;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 20px;
    }

    .sd-lightbox-audio-icon {
      font-size: 48px;
    }

    .sd-lightbox-audio-wrapper audio {
      width: 300px;
    }
  `;

  document.head.appendChild(style);
}

function adjustBrightness(hex: string, amount: number): string {
  if (!HEX_COLOR_RE.test(hex)) {
    return hex;
  }
  const num = parseInt(hex.replace("#", ""), 16);
  const r = Math.max(0, Math.min(255, ((num >> 16) & 0xff) + amount));
  const g = Math.max(0, Math.min(255, ((num >> 8) & 0xff) + amount));
  const b = Math.max(0, Math.min(255, (num & 0xff) + amount));
  return `#${((r << 16) | (g << 8) | b).toString(16).padStart(6, "0")}`;
}
