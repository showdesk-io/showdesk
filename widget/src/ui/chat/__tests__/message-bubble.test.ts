/** A text message's attachments: a mail's files, a file from the conversation page. */

import { describe, expect, it } from "vitest";
import type { ChatMessage } from "../../../types";
import { renderMessageBubble } from "../message-bubble";

function message(body: string, filenames: string[]): ChatMessage {
  return {
    id: "m1",
    ticketId: "t1",
    body,
    bodyType: "text",
    senderType: "user",
    senderName: "",
    attachments: filenames.map((filename, i) => ({
      id: `a${i}`,
      url: `https://files.test/${filename}`,
      filename,
      contentType: "application/octet-stream",
      fileSize: 10,
    })),
    createdAt: "2026-11-03T13:23:31Z",
  };
}

const links = (el: HTMLElement) =>
  [...el.querySelectorAll<HTMLAnchorElement>("a.sd-msg-file-link")].map((a) => [
    a.textContent?.trim(),
    a.getAttribute("href"),
  ]);

describe("a text message with attachments", () => {
  it("links every file under the text", () => {
    const el = renderMessageBubble(message("Here are the files.", ["notes.txt", "screen.png"]));

    expect(el.querySelector(".sd-msg-text")?.textContent).toBe("Here are the files.");
    expect(links(el)).toEqual([
      ["📄notes.txt", "https://files.test/notes.txt"],
      ["📄screen.png", "https://files.test/screen.png"],
    ]);
  });

  it("shows the file alone, not an empty bubble, when there's no text", () => {
    const el = renderMessageBubble(message("", ["printer-log.txt"]));

    expect(el.querySelector(".sd-msg-text")).toBeNull();
    expect(links(el)).toEqual([["📄printer-log.txt", "https://files.test/printer-log.txt"]]);
  });

  it("stays plain text without attachments", () => {
    const el = renderMessageBubble(message("Hello", []));

    expect(el.querySelector(".sd-msg-text")?.textContent).toBe("Hello");
    expect(links(el)).toEqual([]);
  });
});
