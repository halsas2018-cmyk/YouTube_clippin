"""YouTube metadata extraction via yt-dlp.

This module wraps the ``yt-dlp`` CLI to fetch basic video metadata.
No video/audio is downloaded — only metadata and caption-track awareness.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Prefer PATH / environment variable, fallback to kinetic_typo_vid venv if on local dev
YTDLP_PATH = os.environ.get("YTDLP_PATH") or shutil.which("yt-dlp") or "/root/kinetic_typo_vid/venv/bin/yt-dlp"

# Optional Netscape-format cookies file for yt-dlp authentication.
# Resolution order:
#   1. YTDLP_COOKIES_FILE env var  (set by CI from the decoded GitHub secret)
#   2. cookies.txt in the project root  (local dev convenience)
# Never commit cookies.txt — it is listed in .gitignore.
_COOKIES_FILE: str | None = os.environ.get("YTDLP_COOKIES_FILE") or (
    str(Path(__file__).resolve().parent.parent.parent / "cookies.txt")
    if (Path(__file__).resolve().parent.parent.parent / "cookies.txt").exists()
    else None
)

# Player clients to try in order. tv/web_creator don't require sign-in on CI runners.
_METADATA_PLAYER_CLIENTS = [
    "tv,web_creator",
    "tv_embedded,mweb",
    "android,ios",
    "web",
]


def _ensure_yt_dlp() -> None:
    """Raise FileNotFoundError if yt-dlp is not available."""
    if not shutil.which(YTDLP_PATH):
        raise FileNotFoundError(
            f"yt-dlp not found at {YTDLP_PATH}. "
            "Ensure yt-dlp is installed and available on PATH."
        )


def _run_ytdlp_metadata(url: str, player_clients: str) -> subprocess.CompletedProcess:
    """Run yt-dlp --dump-json with the given player_clients extractor arg.

    Passes ``--cookies`` when a cookies file is configured, to bypass YouTube
    bot-detection / sign-in checks on CI runners.
    """
    cmd = [
        YTDLP_PATH,
        "--dump-json",
        "--no-warnings",
        "--no-playlist",
        "--extractor-args",
        f"youtube:player_client={player_clients}",
    ]
    if _COOKIES_FILE:
        cmd += ["--cookies", _COOKIES_FILE]
        sys.stderr.write(f"[yt-dlp] Using cookies file: {_COOKIES_FILE}\n")
    cmd.append(url)
    return subprocess.run(cmd, capture_output=True, text=True)


def fetch_metadata(url: str) -> dict:
    """Fetch video metadata using ``yt-dlp --dump-json``.

    Tries multiple player clients in order to work around YouTube bot-detection
    on CI/cloud runners (GitHub Actions, etc.).

    Args:
        url: YouTube video URL.

    Returns:
        Parsed metadata dict from yt-dlp's JSON output.

    Raises:
        FileNotFoundError: If yt-dlp is not installed.
        RuntimeError: If all player client attempts fail.
        ValueError: If yt-dlp produces no output (invalid URL / unavailable video).
    """
    _ensure_yt_dlp()

    last_error: Exception | None = None
    for clients in _METADATA_PLAYER_CLIENTS:
        sys.stderr.write(f"[yt-dlp] Trying player_client={clients} ...\n")
        result = _run_ytdlp_metadata(url, clients)
        if result.returncode == 0 and result.stdout.strip():
            sys.stderr.write(f"[yt-dlp] Success with player_client={clients}\n")
            return json.loads(result.stdout.strip())

        sys.stderr.write(f"[yt-dlp] Failed with player_client={clients}: {result.stderr.strip()[:200]}\n")
        last_error = subprocess.CalledProcessError(result.returncode, result.args, result.stderr)

    # All clients failed — raise the last error
    raise RuntimeError(
        f"yt-dlp failed to fetch metadata for {url} with all player clients "
        f"({', '.join(_METADATA_PLAYER_CLIENTS)}). "
        f"Last error: {last_error}"
    )


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
