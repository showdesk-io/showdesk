/**
 * Qualification step: issue type selection + bug visibility follow-up.
 *
 * Renders 4 issue type buttons (bug, question, suggestion, other).
 * If "bug" is selected, shows a follow-up asking whether the problem
 * is visible on screen. Other types proceed directly.
 */

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
