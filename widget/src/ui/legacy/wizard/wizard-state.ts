/**
 * Wizard state machine for the multi-step support flow.
 *
 * Manages wizard state and provides helper functions for
 * issue-type-dependent branching (capture options, placeholders,
 * follow-up questions).
 */

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
