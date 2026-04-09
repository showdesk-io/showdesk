/**
 * Audio Recorder — Tap-to-record / tap-to-stop inline audio messages.
 *
 * Uses MediaRecorder API with audio-only stream.
 * Produces audio/webm blobs.
 */

export interface AudioRecorderController {
  /** Start recording. Returns false if permission denied. */
  start: () => Promise<boolean>;
  /** Stop recording. Returns the audio blob. */
  stop: () => Blob | null;
  /** Whether currently recording. */
  isRecording: () => boolean;
  /** Clean up resources. */
  destroy: () => void;
}

export function createAudioRecorder(
  onStateChange: (recording: boolean, duration: number) => void,
): AudioRecorderController {
  let mediaRecorder: MediaRecorder | null = null;
  let stream: MediaStream | null = null;
  let chunks: Blob[] = [];
  let recording = false;
  let startTime = 0;
  let timerInterval: ReturnType<typeof setInterval> | null = null;
  let resultBlob: Blob | null = null;

  async function start(): Promise<boolean> {
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      return false;
    }

    chunks = [];
    resultBlob = null;
    mediaRecorder = new MediaRecorder(stream, {
      mimeType: getSupportedMimeType(),
    });

    mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunks.push(e.data);
    };

    mediaRecorder.onstop = () => {
      resultBlob = new Blob(chunks, { type: mediaRecorder?.mimeType || "audio/webm" });
      cleanup();
    };

    mediaRecorder.start(100);
    recording = true;
    startTime = Date.now();
    timerInterval = setInterval(() => {
      onStateChange(true, Math.floor((Date.now() - startTime) / 1000));
    }, 1000);
    onStateChange(true, 0);
    return true;
  }

  function stop(): Blob | null {
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
      mediaRecorder.stop();
    }
    recording = false;
    onStateChange(false, 0);
    // Return the blob synchronously from chunks if onstop hasn't fired yet
    if (!resultBlob && chunks.length > 0) {
      resultBlob = new Blob(chunks, { type: "audio/webm" });
    }
    return resultBlob;
  }

  function isRecording(): boolean {
    return recording;
  }

  function cleanup(): void {
    if (timerInterval) {
      clearInterval(timerInterval);
      timerInterval = null;
    }
    if (stream) {
      stream.getTracks().forEach((t) => t.stop());
      stream = null;
    }
    recording = false;
  }

  function destroy(): void {
    if (recording) stop();
    cleanup();
  }

  return { start, stop, isRecording, destroy };
}

function getSupportedMimeType(): string {
  const types = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"];
  for (const type of types) {
    if (MediaRecorder.isTypeSupported(type)) return type;
  }
  return "audio/webm";
}
