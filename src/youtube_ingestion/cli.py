"""Command-line entry point for YouTube ingestion.

Usage (from project root)::

    python -m src.youtube_ingestion <youtube-url>
    python -m src.youtube_ingestion <youtube-url> --languages en
"""
import argparse
import json
import sys
from pathlib import Path

import yaml

from .ingester import Ingester

# Project root is three levels up from this file:
#   src/youtube_ingestion/cli.py  →  src/youtube_ingestion/  →  src/  →  <project_root>
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_config() -> dict:
    """Load pipeline configuration from ``config/pipeline.yaml``.

    Returns an empty dict if the file does not exist.
    """
    config_path = _PROJECT_ROOT / "config" / "pipeline.yaml"
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    return {}


def main() -> int:
    """CLI entry point — returns process exit code."""
    parser = argparse.ArgumentParser(
        prog="youtube-ingest",
        description="Ingest a YouTube video: metadata + transcripts with timestamps",
    )
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument(
        "--languages",
        nargs="*",
        default=["en"],
        help="Caption language codes to fetch (default: en)",
    )
    parser.add_argument(
        "--download-dir",
        default=None,
        help="Override download directory (default: from config or media/downloads)",
    )
    args = parser.parse_args()

    config = _load_config()
    download_dir = (
        Path(args.download_dir)
        if args.download_dir
        else Path(config.get("youtube", {}).get("download_dir", "media/downloads"))
    )

    ingester = Ingester(download_dir=download_dir)

    try:
        result = ingester.ingest(args.url, languages=args.languages)
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(json.dumps({
        "video_id": result.video_id,
        "metadata_path": str(result.metadata_path),
        "transcript_paths": [str(p) for p in result.transcript_paths],
        "languages": result.languages,
        "warnings": result.warnings,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
