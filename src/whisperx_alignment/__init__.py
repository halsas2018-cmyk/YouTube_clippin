"""WhisperX alignment stage.

Aligns extracted section MP4 files using WhisperX to produce word-level
timestamps with both local (section-relative) and global (original-video)
coordinates.

Usage:
    python -m whisperx_alignment.align_sections FltNsyPXNdo
    python -m whisperx_alignment.verify_alignment FltNsyPXNdo
"""

from .align_sections import align_video_id, extract_words_with_timestamps

__all__ = ["align_video_id", "extract_words_with_timestamps"]
