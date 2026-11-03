/**
 * Email proof banner — a code mailed to the session's email opens the conversations
 * held under that address.
 *
 * The same banner for any unproven email, whatever exists behind it: the address is
 * only declared, and a count would tell anyone whether it's a customer's. For the same
 * reason a wrong code gets one message, whatever the cause.
 */

import { requestEmailCode, verifyEmailCode } from "../../api/chat-api";
import type { WidgetStore } from "../../state/widget-state";
import type { ShowdeskConfig } from "../../types";

const RESEND_AFTER_MS = 60_000;
const CODE_LENGTH = 6;
const WRONG_CODE = "That code didn't work. Check it, or get a new one.";
const NOT_SENT = "Couldn't ask for a code. Try again in a moment.";

function element<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className: string,
  text = "",
): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  el.className = className;
  if (text) el.textContent = text;
  return el;
}

/** Render the banner. `onProven` runs once the email is proven, to refresh the list. */
export function renderEmailProofBanner(
  store: WidgetStore,
  config: ShowdeskConfig,
  onProven: () => void,
): HTMLElement {
  const banner = element("div", "sd-email-proof");
  const sessionId = store.state.session?.sessionId;
  let timer: ReturnType<typeof setInterval> | null = null;
  // What the banner shows: a code asked for, and for which email.
  let shownSentAt = store.state.emailCodeSentAt;
  let shownEmail = store.state.session?.email;

  // A new email, or a code dropped elsewhere (another session, the contact form):
  // what's on screen is about something else now.
  const unsubscribe = store.subscribe(() => {
    const session = store.state.session;
    const gone = !banner.isConnected;
    if (gone || !session || session.sessionId !== sessionId || !session.emailProofOffered) {
      // Taken off with its view, or nothing to offer this session any more.
      unsubscribe();
      if (timer) clearInterval(timer);
      timer = null;
      banner.remove();
      return;
    }
    if (store.state.emailCodeSentAt !== shownSentAt || session.email !== shownEmail) render();
  });

  const stillHere = () => banner.isConnected && store.state.session?.sessionId === sessionId;

  function showError(error: HTMLElement, text: string): void {
    error.textContent = text;
    error.hidden = false;
  }

  function render(): void {
    if (timer) clearInterval(timer);
    timer = null;
    shownSentAt = store.state.emailCodeSentAt;
    shownEmail = store.state.session?.email;
    banner.replaceChildren();
    if (store.state.emailCodeSentAt === null) renderOffer();
    else renderCodeForm();
  }

  function renderOffer(): void {
    banner.appendChild(
      element("div", "sd-email-proof-text", "Have earlier conversations by email?"),
    );
    const ask = element("button", "sd-btn-small sd-btn-primary", "Get a code");
    const error = element("div", "sd-email-proof-error");
    error.hidden = true;
    ask.onclick = () => void askForCode(ask, error);
    banner.append(ask, error);
  }

  function renderCodeForm(): void {
    const email = store.state.session?.email ?? "";
    banner.appendChild(
      element(
        "div",
        "sd-email-proof-text",
        `If you have conversations by email, a code is on its way to ${email}.`,
      ),
    );

    const form = element("div", "sd-email-proof-form");
    const input = element("input", "sd-input sd-email-proof-code");
    input.type = "text";
    input.inputMode = "numeric";
    input.autocomplete = "one-time-code";
    input.maxLength = CODE_LENGTH;
    input.placeholder = "6-digit code";
    input.setAttribute("aria-label", "Code");
    const verify = element("button", "sd-btn-small sd-btn-primary", "Verify");
    form.append(input, verify);

    const resend = element("button", "sd-btn-small sd-btn-link sd-email-proof-resend");
    const error = element("div", "sd-email-proof-error");
    error.hidden = true;

    const updateResend = () => {
      const sentAt = store.state.emailCodeSentAt ?? 0;
      const left = Math.ceil((sentAt + RESEND_AFTER_MS - Date.now()) / 1000);
      resend.disabled = left > 0;
      resend.textContent = left > 0 ? `Resend in ${left} s` : "Resend code";
      if (left <= 0 && timer) {
        clearInterval(timer);
        timer = null;
      }
    };
    updateResend();
    timer = setInterval(() => {
      if (!banner.isConnected) {
        if (timer) clearInterval(timer);
        timer = null;
        return;
      }
      updateResend();
    }, 1000);

    resend.onclick = () => void askForCode(resend, error);
    verify.onclick = () => void submit(input, verify, error);
    input.onkeydown = (event) => {
      if (event.key === "Enter") void submit(input, verify, error);
    };
    banner.append(form, resend, error);
  }

  async function askForCode(button: HTMLButtonElement, error: HTMLElement): Promise<void> {
    if (!sessionId) return;
    button.disabled = true;
    try {
      await requestEmailCode(config, sessionId);
      if (!stillHere()) return;
      // Shown by the subscription.
      store.update({ emailCodeSentAt: Date.now() });
    } catch {
      if (!stillHere()) return;
      button.disabled = false;
      showError(error, NOT_SENT);
    }
  }

  async function submit(
    input: HTMLInputElement,
    button: HTMLButtonElement,
    error: HTMLElement,
  ): Promise<void> {
    const session = store.state.session;
    if (!session || session.sessionId !== sessionId || button.disabled) return;
    const code = input.value.trim();
    let proven = false;
    button.disabled = true;
    try {
      proven = code.length === CODE_LENGTH && (await verifyEmailCode(config, sessionId, code));
    } catch {
      proven = false;
    }
    if (!stillHere()) return;
    button.disabled = false;
    if (!proven) {
      showError(error, WRONG_CODE);
      // A refused code may be spent: a new one can be asked for at once.
      if (timer) clearInterval(timer);
      timer = null;
      const resend = banner.querySelector<HTMLButtonElement>(".sd-email-proof-resend");
      if (resend) {
        resend.disabled = false;
        resend.textContent = "Get a new code";
      }
      return;
    }
    if (timer) clearInterval(timer);
    unsubscribe();
    store.update({
      session: { ...session, emailProofOffered: false },
      emailCodeSentAt: null,
    });
    banner.remove();
    onProven();
  }

  render();
  return banner;
}
