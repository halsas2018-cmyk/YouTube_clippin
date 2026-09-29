"""YouTube metadata extraction via yt-dlp.

This module wraps the ``yt-dlp`` CLI to fetch basic video metadata.
No video/audio is downloaded — only metadata and caption-track awareness.
"""
import json
import shutil
import subprocess

# Explicit path to yt-dlp in the kinetic_typo_vid venv — do NOT resolve from PATH.
YTDLP_PATH = "/root/kinetic_typo_vid/venv/bin/yt-dlp"


def _ensure_yt_dlp() -> None:
    """Raise FileNotFoundError if yt-dlp is not available at the explicit path."""
    if not shutil.which(YTDLP_PATH):
        raise FileNotFoundError(
            f"yt-dlp not found at {YTDLP_PATH}. "
            "Ensure the virtual environment is populated."
        )


def fetch_metadata(url: str) -> dict:
    """Fetch video metadata using ``yt-dlp --dump-json``.

    Args:
        url: YouTube video URL.

    Returns:
        Parsed metadata dict from yt-dlp's JSON output.

    Raises:
        FileNotFoundError: If yt-dlp is not installed.
        subprocess.CalledProcessError: If yt-dlp exits non-zero.
        ValueError: If yt-dlp produces no output (invalid URL / unavailable video).
    """
    _ensure_yt_dlp()
    result = subprocess.run(
        [YTDLP_PATH, "--dump-json", "--no-warnings", "--no-playlist", "-f", "bestvideo[vcodec^=avc1]+bestaudio[acodec^=mp4a]/best", url],
        capture_output=True,
        text=True,
        check=True,
    )
    stdout = result.stdout.strip()
    if not stdout:
        raise ValueError(
            "yt-dlp returned no output — the URL may be invalid "
            "or the video may be unavailable."
        )
    return json.loads(stdout)


def extract_video_id(metadata: dict) -> str:
    """Extract the video ID from yt-dlp metadata."""
    return metadata["id"]


def extract_caption_languages(metadata: dict) -> list[str]:
    """Extract available caption language codes from yt-dlp metadata.

    Combines both manually created *subtitles* and auto-generated captions
    into a single sorted list of language codes.
    """
    subtitles = metadata.get("subtitles") or {}
    auto_captions = metadata.get("automatic_captions") or {}
    all_langs = set(subtitles.keys()) | set(auto_captions.keys())
    return sorted(all_langs)
