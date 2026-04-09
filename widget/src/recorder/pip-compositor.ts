/**
 * Canvas-based Picture-in-Picture compositor.
 *
 * Draws the screen capture and a circular camera bubble onto an offscreen
 * canvas at ~30fps, producing a single composited MediaStream for the
 * MediaRecorder. This gives a Loom-style webcam overlay on the recording.
 */

export type BubblePosition = "top-left" | "top-right" | "bottom-left" | "bottom-right";
export type BubbleSize = "large" | "mini";

export class PipCompositor {
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private screenVideo: HTMLVideoElement;
  private cameraVideo: HTMLVideoElement;
  private animationId: number | null = null;
  private _position: BubblePosition = "bottom-right";
  private _size: BubbleSize = "large";
  private _cameraEnabled = true;
  private _stream: MediaStream | null = null;

  constructor(
    screenStream: MediaStream,
    cameraStream: MediaStream,
    width: number,
    height: number,
  ) {
    this.canvas = document.createElement("canvas");
    this.canvas.width = width;
    this.canvas.height = height;
    this.ctx = this.canvas.getContext("2d")!;

    this.screenVideo = document.createElement("video");
    this.screenVideo.srcObject = screenStream;
    this.screenVideo.muted = true;
    this.screenVideo.playsInline = true;

    this.cameraVideo = document.createElement("video");
    this.cameraVideo.srcObject = cameraStream;
    this.cameraVideo.muted = true;
    this.cameraVideo.playsInline = true;
  }

  /** The composited stream (screen + camera bubble) at 30fps. */
  get stream(): MediaStream {
    if (!this._stream) {
      this._stream = this.canvas.captureStream(30);
    }
    return this._stream;
  }

  set position(pos: BubblePosition) {
    this._position = pos;
  }
  get position(): BubblePosition {
    return this._position;
  }

  set size(s: BubbleSize) {
    this._size = s;
  }
  get size(): BubbleSize {
    return this._size;
  }

  get cameraEnabled(): boolean {
    return this._cameraEnabled;
  }

  toggleCamera(): void {
    this._cameraEnabled = !this._cameraEnabled;
  }

  toggleSize(): void {
    this._size = this._size === "large" ? "mini" : "large";
  }

  /** Start playing source videos and kick off the render loop. */
  async start(): Promise<void> {
    await Promise.all([this.screenVideo.play(), this.cameraVideo.play()]);
    this.render();
  }

  /** Pause the render loop (does not stop streams). */
  stop(): void {
    if (this.animationId) {
      cancelAnimationFrame(this.animationId);
      this.animationId = null;
    }
  }

  /** Stop rendering and release video element references. */
  destroy(): void {
    this.stop();
    this._stream = null;
    this.screenVideo.srcObject = null;
    this.cameraVideo.srcObject = null;
  }

  // ---- Private rendering ----

  private render = (): void => {
    const { width, height } = this.canvas;

    // 1. Draw screen capture, scaled to fill the entire canvas
    this.ctx.drawImage(this.screenVideo, 0, 0, width, height);

    // 2. Draw circular camera bubble when enabled
    if (this._cameraEnabled) {
      const radius = this._size === "large" ? 60 : 30;
      const margin = 16;
      const { x, y } = this.getBubbleCenter(radius, margin);

      // Circular clip then draw camera frame
      this.ctx.save();
      this.ctx.beginPath();
      this.ctx.arc(x, y, radius, 0, Math.PI * 2);
      this.ctx.clip();

      // Crop camera to a centered square so it fills the circle evenly
      const vw = this.cameraVideo.videoWidth || 320;
      const vh = this.cameraVideo.videoHeight || 240;
      const cropSize = Math.min(vw, vh);
      const sx = (vw - cropSize) / 2;
      const sy = (vh - cropSize) / 2;
      this.ctx.drawImage(
        this.cameraVideo,
        sx,
        sy,
        cropSize,
        cropSize,
        x - radius,
        y - radius,
        radius * 2,
        radius * 2,
      );
      this.ctx.restore();

      // White border ring
      this.ctx.beginPath();
      this.ctx.arc(x, y, radius, 0, Math.PI * 2);
      this.ctx.strokeStyle = "white";
      this.ctx.lineWidth = 3;
      this.ctx.stroke();
    }

    this.animationId = requestAnimationFrame(this.render);
  };

  private getBubbleCenter(
    radius: number,
    margin: number,
  ): { x: number; y: number } {
    const d = radius + margin;
    switch (this._position) {
      case "top-left":
        return { x: d, y: d };
      case "top-right":
        return { x: this.canvas.width - d, y: d };
      case "bottom-left":
        return { x: d, y: this.canvas.height - d };
      case "bottom-right":
        return { x: this.canvas.width - d, y: this.canvas.height - d };
    }
  }
}
