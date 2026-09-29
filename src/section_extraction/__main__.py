"""CLI entry point for the section-extraction stage.

Usage (from project root)::

    # Pad ranges and extract section media:
    python -m src.section_extraction <video_id>

    # Pad ranges only without downloading media:
    python -m src.section_extraction <video_id> --pad-only

    # Extract media only from existing padded ranges:
    python -m src.section_extraction <video_id> --extract-only
"""
from __future__ import annotations

import argparse
import json
import sys

from .extractor import extract_sections
from .range_padding import (
    DEFAULT_OUTPUT_FILENAME,
    DEFAULT_PADDING_SECONDS,
    run_range_padding,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="section-extraction",
        description="Add padding to candidate ranges and extract padded section media.",
    )
    parser.add_argument(
        "video_id",
        help="YouTube video ID whose sections to extract (e.g. FltNsyPXNdo)",
    )
    parser.add_argument(
        "--padding",
        type=float,
        default=DEFAULT_PADDING_SECONDS,
        help=f"Seconds of padding to add before and after each range (default: {DEFAULT_PADDING_SECONDS})",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=DEFAULT_OUTPUT_FILENAME,
        help=f"Padded ranges output filename in downloads directory (default: {DEFAULT_OUTPUT_FILENAME})",
    )
    parser.add_argument(
        "--video-duration",
        type=float,
        default=None,
        help="Optional override for original video duration (clamping limit)",
    )
    parser.add_argument(
        "--pad-only",
        action="store_true",
        help="Only compute and write padded ranges without extracting media",
    )
    parser.add_argument(
        "--extract-only",
        action="store_true",
        help="Only extract media for already-computed padded ranges",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-download and overwrite existing extracted sections",
    )

    args = parser.parse_args()

    try:
        if not args.extract_only:
            output_path = run_range_padding(
                video_id=args.video_id,
                padding_seconds=args.padding,
                video_duration=args.video_duration,
                output_filename=args.output,
            )
            print(f"Padded ranges ready: {output_path}")

        if not args.pad_only:
            print(f"Extracting padded sections for video {args.video_id}...")
            sections = extract_sections(
                video_id=args.video_id,
                padded_ranges_filename=args.output,
                overwrite=args.overwrite,
            )
            print(f"Successfully extracted {len(sections)} sections:")
            for s in sections:
                print(
                    f"  [{s.section_id}] {s.file_name}: "
                    f"offset {s.start_offset:.2f}s -> {s.end_offset:.2f}s "
                    f"(target {s.target_duration_s:.2f}s, probed {s.probed_duration_s:.2f}s)"
                )

    except Exception as exc:  # noqa: BLE001
        print(f"Error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
