/**
 * Widget CSS styles injected into the host page.
 *
 * All styles are scoped under #showdesk-widget-container to avoid
 * conflicts with the host page's styles. The widget must work in
 * any environment without breaking existing layouts.
 */

export function injectStyles(primaryColor: string): void {
  if (document.getElementById("showdesk-widget-styles")) {
    return;
  }

  const style = document.createElement("style");
  style.id = "showdesk-widget-styles";
  style.textContent = `
    #showdesk-widget-container {
      --sd-primary: ${primaryColor};
      --sd-primary-hover: ${adjustBrightness(primaryColor, -15)};
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

    @keyframes sd-fadeIn {
      from { opacity: 0; }
      to { opacity: 1; }
    }

    @keyframes sd-slideIn {
      from { opacity: 0; transform: translate(-50%, -48%); }
      to { opacity: 1; transform: translate(-50%, -50%); }
    }

    @keyframes sd-pulse {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.5; }
    }
  `;

  document.head.appendChild(style);
}

function adjustBrightness(hex: string, amount: number): string {
  const num = parseInt(hex.replace("#", ""), 16);
  const r = Math.max(0, Math.min(255, ((num >> 16) & 0xff) + amount));
  const g = Math.max(0, Math.min(255, ((num >> 8) & 0xff) + amount));
  const b = Math.max(0, Math.min(255, (num & 0xff) + amount));
  return `#${((r << 16) | (g << 8) | b).toString(16).padStart(6, "0")}`;
}
