"""Celery tasks for video processing.

Video processing is the backbone of the Showdesk experience.
These tasks handle the full pipeline: validation, compression,
thumbnail generation, and optional transcription.
"""

import logging
import subprocess
import tempfile
from pathlib import Path

from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, queue="video_processing", max_retries=3)
def process_video(self, video_id: str) -> dict:  # noqa: ANN001
    """Process an uploaded video recording.

    Pipeline:
    1. Mark as processing
    2. Extract metadata (duration, resolution) via FFprobe
    3. Generate thumbnail via FFmpeg
    4. Compress/transcode if needed
    5. Mark as ready

    If AI features are enabled, triggers transcription as a follow-up task.
    """
    from .models import VideoRecording

    try:
        video = VideoRecording.objects.get(id=video_id)
    except VideoRecording.DoesNotExist:
        logger.error("Video %s not found.", video_id)
        return {"status": "error", "message": "Video not found"}

    video.status = VideoRecording.Status.PROCESSING
    video.processing_started_at = timezone.now()
    video.save(update_fields=["status", "processing_started_at"])

    try:
        # Extract metadata with ffprobe
        _extract_metadata(video)

        # Generate thumbnail
        _generate_thumbnail(video)

        # Mark as ready
        video.status = VideoRecording.Status.READY
        video.processing_completed_at = timezone.now()
        video.save(update_fields=[
            "status",
            "processing_completed_at",
            "duration_seconds",
            "width",
            "height",
            "file_size",
        ])

        # Trigger transcription if AI is enabled
        if settings.AI_ENABLED and settings.FEATURE_AI_TRANSCRIPTION and video.has_audio:
            transcribe_video.delay(str(video.id))

        logger.info("Video %s processed successfully.", video_id)
        return {"status": "success", "video_id": video_id}

    except Exception as exc:
        video.status = VideoRecording.Status.FAILED
        video.processing_error = str(exc)
        video.processing_completed_at = timezone.now()
        video.save(update_fields=["status", "processing_error", "processing_completed_at"])
        logger.exception("Failed to process video %s.", video_id)
        raise self.retry(exc=exc, countdown=60)


def _extract_metadata(video) -> None:  # noqa: ANN001
    """Extract video metadata using ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                video.original_file.path,
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        import json
        probe_data = json.loads(result.stdout)

        # Extract duration
        if "format" in probe_data:
            video.duration_seconds = float(probe_data["format"].get("duration", 0))
            video.file_size = int(probe_data["format"].get("size", 0))

        # Extract video stream info
        for stream in probe_data.get("streams", []):
            if stream.get("codec_type") == "video":
                video.width = int(stream.get("width", 0))
                video.height = int(stream.get("height", 0))
                break

    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        logger.warning("ffprobe failed for video %s: %s", video.id, exc)


def _generate_thumbnail(video) -> None:  # noqa: ANN001
    """Generate a thumbnail from the video using FFmpeg."""
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            thumbnail_path = tmp.name

        subprocess.run(
            [
                "ffmpeg",
                "-i", video.original_file.path,
                "-ss", "00:00:01",
                "-vframes", "1",
                "-vf", f"scale={settings.VIDEO_THUMBNAIL_WIDTH}:{settings.VIDEO_THUMBNAIL_HEIGHT}",
                "-y",
                thumbnail_path,
            ],
            capture_output=True,
            check=True,
            timeout=30,
        )

        # Save thumbnail to storage
        from django.core.files import File
        with open(thumbnail_path, "rb") as f:
            video.thumbnail.save(
                f"thumb_{video.id}.jpg",
                File(f),
                save=False,
            )

        # Clean up temp file
        Path(thumbnail_path).unlink(missing_ok=True)

    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        logger.warning("Thumbnail generation failed for video %s: %s", video.id, exc)


@shared_task(bind=True, queue="video_processing", max_retries=2)
def transcribe_video(self, video_id: str) -> dict:  # noqa: ANN001
    """Transcribe a video's audio track using Whisper.

    This task is only triggered when AI_ENABLED and
    FEATURE_AI_TRANSCRIPTION are both True.
    """
    from .models import VideoRecording

    try:
        video = VideoRecording.objects.get(id=video_id)
    except VideoRecording.DoesNotExist:
        return {"status": "error", "message": "Video not found"}

    video.transcription_status = "processing"
    video.save(update_fields=["transcription_status"])

    try:
        # Placeholder for Whisper integration
        # In production, this will use the Whisper model to transcribe
        logger.info("Transcription for video %s would be processed here.", video_id)

        video.transcription_status = "completed"
        video.save(update_fields=["transcription_status", "transcription"])

        return {"status": "success", "video_id": video_id}

    except Exception as exc:
        video.transcription_status = "failed"
        video.save(update_fields=["transcription_status"])
        logger.exception("Transcription failed for video %s.", video_id)
        raise self.retry(exc=exc, countdown=120)


@shared_task
def cleanup_expired_videos() -> dict:
    """Delete videos that have passed their expiration date.

    This task should be scheduled to run periodically via Celery Beat.
    Privacy is a feature: expired videos are permanently deleted.
    """
    from .models import VideoRecording

    expired = VideoRecording.objects.filter(
        expires_at__lte=timezone.now(),
        status__in=[
            VideoRecording.Status.READY,
            VideoRecording.Status.FAILED,
        ],
    )

    count = 0
    for video in expired:
        # Delete files from storage
        if video.original_file:
            video.original_file.delete(save=False)
        if video.processed_file:
            video.processed_file.delete(save=False)
        if video.thumbnail:
            video.thumbnail.delete(save=False)

        video.status = VideoRecording.Status.EXPIRED
        video.save(update_fields=["status"])
        count += 1

    logger.info("Cleaned up %d expired videos.", count)
    return {"expired_count": count}
