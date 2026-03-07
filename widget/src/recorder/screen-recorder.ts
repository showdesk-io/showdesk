/**
 * Screen recording using the MediaRecorder API.
 *
 * This is the core differentiator of Showdesk. The recorder captures
 * the user's screen, optionally with camera (picture-in-picture) and
 * microphone audio. It produces a single WebM blob ready for upload.
 *
 * No external dependencies. No LiveKit needed for basic recording.
 * LiveKit integration is reserved for real-time streaming features.
 */

export interface RecorderOptions {
  audio: boolean;
  camera: boolean;
}

export class ScreenRecorder {
  private mediaRecorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private streams: MediaStream[] = [];

  /** Callback invoked when recording stops with the final blob. */
  public onStop: ((blob: Blob) => void) | null = null;

  /**
   * Start recording the screen.
   *
   * Prompts the user for screen sharing permission. If camera is
   * enabled, requests camera access and composites it into the
   * recording via a canvas (future enhancement) or as a separate
   * track for now.
   */
  async start(options: RecorderOptions): Promise<void> {
    this.cleanup();

    // Request screen capture
    const displayStream = await navigator.mediaDevices.getDisplayMedia({
      video: {
        width: { ideal: 1920 },
        height: { ideal: 1080 },
        frameRate: { ideal: 30 },
      },
      audio: options.audio,
    });

    this.streams.push(displayStream);

    const tracks: MediaStreamTrack[] = [...displayStream.getTracks()];

    // Request microphone if audio enabled and not already captured
    if (options.audio && !displayStream.getAudioTracks().length) {
      try {
        const audioStream = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
          },
        });
        this.streams.push(audioStream);
        tracks.push(...audioStream.getAudioTracks());
      } catch (err) {
        console.warn("[Showdesk] Microphone access denied:", err);
      }
    }

    // Request camera if enabled
    if (options.camera) {
      try {
        const cameraStream = await navigator.mediaDevices.getUserMedia({
          video: {
            width: { ideal: 320 },
            height: { ideal: 240 },
            facingMode: "user",
          },
        });
        this.streams.push(cameraStream);
        tracks.push(...cameraStream.getVideoTracks());
      } catch (err) {
        console.warn("[Showdesk] Camera access denied:", err);
      }
    }

    // Create combined stream
    const combinedStream = new MediaStream(tracks);

    // Determine best supported MIME type
    const mimeType = this.getSupportedMimeType();

    this.mediaRecorder = new MediaRecorder(combinedStream, {
      mimeType,
      videoBitsPerSecond: 2500000,
    });

    this.chunks = [];

    this.mediaRecorder.ondataavailable = (event: BlobEvent) => {
      if (event.data.size > 0) {
        this.chunks.push(event.data);
      }
    };

    this.mediaRecorder.onstop = () => {
      const blob = new Blob(this.chunks, { type: mimeType });
      this.cleanup();
      this.onStop?.(blob);
    };

    // Stop recording if user ends screen share
    displayStream.getVideoTracks().forEach((track) => {
      track.onended = () => this.stop();
    });

    this.mediaRecorder.start(1000); // Collect data every second
  }

  /**
   * Stop the current recording.
   */
  stop(): void {
    if (this.mediaRecorder && this.mediaRecorder.state !== "inactive") {
      this.mediaRecorder.stop();
    }
  }

  /**
   * Check if recording is currently active.
   */
  get isRecording(): boolean {
    return this.mediaRecorder?.state === "recording";
  }

  /**
   * Clean up all media streams and resources.
   */
  private cleanup(): void {
    this.streams.forEach((stream) => {
      stream.getTracks().forEach((track) => track.stop());
    });
    this.streams = [];
    this.mediaRecorder = null;
    this.chunks = [];
  }

  /**
   * Get the best supported MIME type for recording.
   */
  private getSupportedMimeType(): string {
    const types = [
      "video/webm;codecs=vp9,opus",
      "video/webm;codecs=vp8,opus",
      "video/webm;codecs=vp9",
      "video/webm;codecs=vp8",
      "video/webm",
      "video/mp4",
    ];

    for (const type of types) {
      if (MediaRecorder.isTypeSupported(type)) {
        return type;
      }
    }

    return "video/webm";
  }
}
