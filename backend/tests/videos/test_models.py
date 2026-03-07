"""Tests for video models."""

import pytest
from django.utils import timezone

from apps.videos.models import VideoRecording
from tests.factories import VideoRecordingFactory


@pytest.mark.django_db
class TestVideoRecording:
    """Tests for the VideoRecording model."""

    def test_create_video(self) -> None:
        """Test basic video creation."""
        video = VideoRecordingFactory()
        assert video.status == VideoRecording.Status.READY
        assert video.ticket is not None
        assert video.duration_seconds == 30.0

    def test_is_playable_when_ready(self) -> None:
        """Test that ready videos are playable."""
        video = VideoRecordingFactory(status=VideoRecording.Status.READY)
        assert video.is_playable is True

    def test_is_not_playable_when_processing(self) -> None:
        """Test that processing videos are not playable."""
        video = VideoRecordingFactory(status=VideoRecording.Status.PROCESSING)
        assert video.is_playable is False

    def test_is_not_playable_when_expired(self) -> None:
        """Test that expired videos are not playable."""
        video = VideoRecordingFactory(status=VideoRecording.Status.EXPIRED)
        assert video.is_playable is False

    def test_video_expiration(self) -> None:
        """Test that videos have an expiration date."""
        video = VideoRecordingFactory()
        assert video.expires_at is not None
        assert video.expires_at > timezone.now()

    def test_video_str(self) -> None:
        """Test string representation."""
        video = VideoRecordingFactory()
        assert video.ticket.reference in str(video)
        assert "ready" in str(video)

    def test_recording_types(self) -> None:
        """Test all recording type values."""
        for rec_type, _ in VideoRecording.RecordingType.choices:
            video = VideoRecordingFactory(recording_type=rec_type)
            assert video.recording_type == rec_type

    def test_transcription_default_disabled(self) -> None:
        """Test that transcription is disabled by default."""
        video = VideoRecordingFactory()
        assert video.transcription_status == "disabled"
        assert video.transcription == ""
