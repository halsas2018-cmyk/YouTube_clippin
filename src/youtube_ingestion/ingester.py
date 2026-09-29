"""Ingestion orchestrator: fetches metadata + transcripts and persists them.

The :class:`Ingester` ties together :mod:`metadata` and :mod:`captions`,
writing results to a per-video directory under *download_dir*::

    media/downloads/<video_id>/
    ├── metadata.json
    └── transcripts/
        ├── en.json
        └── en_AU.json
"""
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from youtube_transcript_api import TranscriptsDisabled

from .captions import fetch_all_transcripts
from .metadata import (
    extract_caption_languages,
    extract_video_id,
    fetch_metadata,
)


# yt-dlp metadata fields retained for downstream stages.
METADATA_FIELDS = [
    "id",
    "title",
    "description",
    "duration",
    "duration_string",
    "upload_date",
    "channel",
    "channel_id",
    "uploader",
    "uploader_id",
    "view_count",
    "like_count",
    "webpage_url",
    "categories",
    "tags",
    "thumbnail",
    "timestamp",
    "uploader_url",
    "channel_follower_count",
]


@dataclass
class IngestionResult:
    """Outcome of an :meth:`Ingester.ingest` run."""

    video_id: str
    metadata_path: Path
    transcript_paths: list[Path]
    languages: list[str]
    warnings: list[str] = field(default_factory=list)


def _write_json(path: Path, data: dict) -> None:
    """Write *data* as indented JSON to *path*, creating parents as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


class Ingester:
    """Orchestrates YouTube ingestion: metadata + transcripts."""

    def __init__(self, download_dir: Path = Path("media/downloads")):
        self.download_dir = download_dir

    def ingest(
        self,
        url: str,
        languages: list[str] | None = None,
    ) -> IngestionResult:
        """Ingest a YouTube video: fetch metadata and transcripts, save to disk.

        Args:
            url: YouTube video URL.
            languages: Optional list of caption language codes to fetch.
                If *None*, all available transcripts are retrieved.

        Returns:
            :class:`IngestionResult` with paths to saved files and any warnings.
        """
        print(f"[ingest] Fetching metadata for: {url}", file=sys.stderr)

        # --- Step 1: Fetch metadata via yt-dlp ---
        raw_metadata = fetch_metadata(url)
        video_id = extract_video_id(raw_metadata)

        # --- Prepare output directory ---
        output_dir = self.download_dir / video_id
        output_dir.mkdir(parents=True, exist_ok=True)

        # --- Step 2: Save metadata ---
        clean_metadata = {
            k: raw_metadata.get(k)
            for k in METADATA_FIELDS
            if k in raw_metadata
        }
        clean_metadata["url"] = url
        clean_metadata["available_caption_languages"] = extract_caption_languages(raw_metadata)

        metadata_path = output_dir / "metadata.json"
        _write_json(metadata_path, clean_metadata)

        # --- Step 3: Fetch and save transcripts ---
        transcript_paths: list[Path] = []
        languages_saved: list[str] = []
        warnings: list[str] = []

        transcripts_dir = output_dir / "transcripts"

        try:
            print(f"[ingest] Extracting transcripts for video: {video_id}", file=sys.stderr)
            transcripts = fetch_all_transcripts(video_id, languages=languages)
            for transcript in transcripts:
                lang_code = transcript["language_code"]
                safe_name = lang_code.replace("-", "_")
                path = transcripts_dir / f"{safe_name}.json"
                _write_json(path, transcript)
                transcript_paths.append(path)
                languages_saved.append(lang_code)
        except TranscriptsDisabled:
            warnings.append("Transcripts are disabled for this video.")
        except Exception as exc:  # noqa: BLE001 — report, don't crash
            warnings.append(
                f"Transcript fetch failed: {type(exc).__name__}: {exc}"
            )

        if languages is not None and not transcript_paths:
            warnings.append(
                f"No transcripts found for requested languages: {languages}"
            )

        return IngestionResult(
            video_id=video_id,
            metadata_path=metadata_path,
            transcript_paths=transcript_paths,
            languages=languages_saved,
            warnings=warnings,
        )
