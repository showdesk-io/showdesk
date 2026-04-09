/**
 * Attachment Menu — Popup with capture options.
 *
 * Screenshot, File/Photo, Video recording, Audio message.
 */

export interface AttachmentMenuCallbacks {
  onScreenshot: () => void;
  onFile: () => void;
  onVideo: () => void;
  onAudio: () => void;
}

export function renderAttachmentMenu(
  callbacks: AttachmentMenuCallbacks,
  anchorEl: HTMLElement,
): HTMLElement {
  // Remove any existing menu
  document.getElementById("sd-attach-menu")?.remove();

  const menu = document.createElement("div");
  menu.id = "sd-attach-menu";
  menu.className = "sd-attach-menu";

  const items: Array<{ icon: string; label: string; action: () => void }> = [
    { icon: "📷", label: "Screenshot", action: callbacks.onScreenshot },
    { icon: "📎", label: "File", action: callbacks.onFile },
    { icon: "🎬", label: "Video", action: callbacks.onVideo },
    { icon: "🎤", label: "Audio", action: callbacks.onAudio },
  ];

  for (const item of items) {
    const btn = document.createElement("button");
    btn.className = "sd-attach-menu-item";
    btn.innerHTML = `<span class="sd-attach-icon">${item.icon}</span><span>${item.label}</span>`;
    btn.onclick = (e) => {
      e.stopPropagation();
      menu.remove();
      item.action();
    };
    menu.appendChild(btn);
  }

  // Position above the anchor
  const rect = anchorEl.getBoundingClientRect();
  menu.style.position = "absolute";
  menu.style.bottom = `${rect.height + 8}px`;
  menu.style.left = "0";

  // Close on outside click
  const closeHandler = (e: MouseEvent) => {
    if (!menu.contains(e.target as Node)) {
      menu.remove();
      document.removeEventListener("click", closeHandler);
    }
  };
  setTimeout(() => document.addEventListener("click", closeHandler), 0);

  return menu;
}
