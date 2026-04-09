/**
 * Media Lightbox — Full-screen overlay for previewing media.
 *
 * Shows images, audio, or video in a centered popup at 90% viewport
 * with a dark overlay. Closes on X button, overlay click, or Escape.
 */

export type LightboxMediaType = "image" | "screenshot" | "audio" | "video";

export function openLightbox(
  url: string,
  mediaType: LightboxMediaType,
  alt?: string,
): void {
  // Remove any existing lightbox
  closeLightbox();

  const overlay = document.createElement("div");
  overlay.id = "sd-lightbox";
  overlay.className = "sd-lightbox-overlay";

  const container = document.createElement("div");
  container.className = "sd-lightbox-container";

  // Close button
  const closeBtn = document.createElement("button");
  closeBtn.className = "sd-lightbox-close";
  closeBtn.innerHTML = "×";
  closeBtn.title = "Close";
  closeBtn.onclick = closeLightbox;

  // Media content
  const media = document.createElement("div");
  media.className = "sd-lightbox-media";

  switch (mediaType) {
    case "image":
    case "screenshot": {
      const img = document.createElement("img");
      img.src = url;
      img.alt = alt || "Preview";
      media.appendChild(img);
      break;
    }
    case "video": {
      const video = document.createElement("video");
      video.src = url;
      video.controls = true;
      video.autoplay = true;
      media.appendChild(video);
      break;
    }
    case "audio": {
      const wrapper = document.createElement("div");
      wrapper.className = "sd-lightbox-audio-wrapper";
      wrapper.innerHTML = `<div class="sd-lightbox-audio-icon">🎤</div>`;
      const audio = document.createElement("audio");
      audio.src = url;
      audio.controls = true;
      audio.autoplay = true;
      wrapper.appendChild(audio);
      media.appendChild(wrapper);
      break;
    }
  }

  container.appendChild(closeBtn);
  container.appendChild(media);
  overlay.appendChild(container);

  // Close on overlay click (but not on media click)
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeLightbox();
  });

  // Close on Escape
  const escHandler = (e: KeyboardEvent) => {
    if (e.key === "Escape") closeLightbox();
  };
  document.addEventListener("keydown", escHandler);
  (overlay as unknown as Record<string, unknown>)._escHandler = escHandler;

  // Add to widget container or body
  const widgetContainer = document.getElementById("showdesk-widget-container");
  (widgetContainer || document.body).appendChild(overlay);
}

export function closeLightbox(): void {
  const existing = document.getElementById("sd-lightbox");
  if (existing) {
    const escHandler = (existing as unknown as Record<string, unknown>)
      ._escHandler as EventListener;
    if (escHandler) {
      document.removeEventListener("keydown", escHandler);
    }
    // Pause any playing media
    existing.querySelectorAll("video, audio").forEach((el) => {
      (el as HTMLMediaElement).pause();
    });
    existing.remove();
  }
}
