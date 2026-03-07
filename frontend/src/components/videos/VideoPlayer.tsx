/**
 * Video player component for ticket recordings.
 *
 * Video is the primary medium in Showdesk. This component provides
 * a first-class playback experience with metadata display.
 */

import type { VideoRecording } from "@/types";

interface VideoPlayerProps {
  video: VideoRecording;
}

export function VideoPlayer({ video }: VideoPlayerProps) {
  if (!video.is_playable) {
    return (
      <div className="flex items-center justify-center rounded-lg bg-gray-100 p-8">
        <div className="text-center">
          {video.status === "processing" && (
            <>
              <div className="mx-auto mb-3 h-8 w-8 animate-spin rounded-full border-2 border-primary-500 border-t-transparent" />
              <p className="text-sm text-gray-500">Processing video...</p>
            </>
          )}
          {video.status === "failed" && (
            <p className="text-sm text-red-500">
              Video processing failed. Please try uploading again.
            </p>
          )}
          {video.status === "expired" && (
            <p className="text-sm text-gray-500">
              This video has expired and is no longer available.
            </p>
          )}
          {video.status === "uploading" && (
            <p className="text-sm text-gray-500">Uploading video...</p>
          )}
        </div>
      </div>
    );
  }

  const videoSrc = video.processed_file || video.original_file;

  return (
    <div className="overflow-hidden rounded-lg bg-black">
      <video
        src={videoSrc}
        controls
        preload="metadata"
        poster={video.thumbnail || undefined}
        className="w-full"
      >
        <track kind="captions" />
      </video>

      {/* Video metadata */}
      <div className="flex items-center justify-between bg-gray-900 px-4 py-2 text-xs text-gray-400">
        <div className="flex items-center gap-3">
          <span>{video.recording_type.replace("_", " + ")}</span>
          {video.has_audio && <span>Audio</span>}
          {video.has_camera && <span>Camera</span>}
        </div>
        {video.duration_seconds != null && (
          <span>
            {Math.floor(video.duration_seconds / 60)}:
            {String(Math.floor(video.duration_seconds % 60)).padStart(2, "0")}
          </span>
        )}
      </div>

      {/* Transcription */}
      {video.transcription && (
        <div className="border-t border-gray-800 bg-gray-900 px-4 py-3">
          <h4 className="mb-1 text-xs font-medium text-gray-400">
            Transcription
          </h4>
          <p className="whitespace-pre-wrap text-sm text-gray-300">
            {video.transcription}
          </p>
        </div>
      )}
    </div>
  );
}
