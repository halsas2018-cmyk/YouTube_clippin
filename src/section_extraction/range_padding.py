"""Range padding stage: add configurable padding to candidate ranges and merge overlaps.

This module takes validated LLM candidate ranges, adds padding (default 8 seconds
before and after each range), clamps them to the video duration, and merges
adjacent/overlapping ranges while preserving chronological order.

The original candidate ranges are preserved unchanged and written alongside the
padded ranges in a separate output file.
"""
from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_PADDING_SECONDS: float = 8.0
DEFAULT_OUTPUT_FILENAME: str = "padded_ranges.json"

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DOWNLOADS_ROOT = _PROJECT_ROOT / "media" / "downloads"


@dataclass
class TimeRange:
    """Represents a time range [start, end] in seconds."""

    start: float
    end: float

    def to_dict(self) -> dict[str, float]:
        return {"start": round(self.start, 2), "end": round(self.end, 2)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TimeRange:
        return cls(start=float(data["start"]), end=float(data["end"]))


def pad_single_range(
    start: float,
    end: float,
    video_duration: float,
    padding_before: float = DEFAULT_PADDING_SECONDS,
    padding_after: float = DEFAULT_PADDING_SECONDS,
) -> TimeRange:
    """Add padding before and after a range, clamped to [0.0, video_duration].

    Parameters
    ----------
    start:
        Start timestamp in seconds.
    end:
        End timestamp in seconds.
    video_duration:
        Original video duration in seconds for upper clamping.
        If <= 0, no upper clamp is applied.
    padding_before:
        Seconds to subtract from start (default 8.0).
    padding_after:
        Seconds to add to end (default 8.0).
    """
    padded_start = max(0.0, float(start) - float(padding_before))
    padded_end = float(end) + float(padding_after)

    if video_duration > 0.0:
        padded_end = min(float(video_duration), padded_end)

    padded_end = max(padded_start, padded_end)
    return TimeRange(start=round(padded_start, 2), end=round(padded_end, 2))


def merge_overlapping_ranges(
    ranges: list[TimeRange | dict[str, Any] | tuple[float, float] | list[float]],
) -> list[TimeRange]:
    """Merge adjacent or overlapping ranges while preserving chronological order.

    Adjacent ranges (where current.start <= previous.end) are merged.
    """
    if not ranges:
        return []

    parsed: list[TimeRange] = []
    for r in ranges:
        if isinstance(r, TimeRange):
            parsed.append(TimeRange(start=r.start, end=r.end))
        elif isinstance(r, dict):
            parsed.append(TimeRange.from_dict(r))
        elif isinstance(r, (tuple, list)) and len(r) == 2:
            parsed.append(TimeRange(start=float(r[0]), end=float(r[1])))
        else:
            raise ValueError(f"Unsupported range format: {r!r}")

    # Sort chronologically by start, then end
    sorted_ranges = sorted(parsed, key=lambda tr: (tr.start, tr.end))

    merged: list[TimeRange] = [
        TimeRange(start=sorted_ranges[0].start, end=sorted_ranges[0].end)
    ]
    for current in sorted_ranges[1:]:
        last = merged[-1]
        # Overlapping or touching / adjacent
        if current.start <= last.end:
            last.end = round(max(last.end, current.end), 2)
        else:
            merged.append(TimeRange(start=current.start, end=current.end))

    return merged


def pad_and_merge_ranges(
    ranges: list[TimeRange | dict[str, Any] | tuple[float, float] | list[float]],
    video_duration: float,
    padding_seconds: float = DEFAULT_PADDING_SECONDS,
    padding_before: float | None = None,
    padding_after: float | None = None,
) -> list[dict[str, float]]:
    """Pad each range and merge adjacent/overlapping ranges chronologically.

    Returns a list of dicts with 'start' and 'end' keys rounded to 2 decimals.
    """
    pad_b = padding_before if padding_before is not None else padding_seconds
    pad_a = padding_after if padding_after is not None else padding_seconds

    padded_ranges: list[TimeRange] = []
    for r in ranges:
        if isinstance(r, TimeRange):
            s, e = r.start, r.end
        elif isinstance(r, dict):
            s, e = float(r["start"]), float(r["end"])
        elif isinstance(r, (tuple, list)) and len(r) == 2:
            s, e = float(r[0]), float(r[1])
        else:
            raise ValueError(f"Unsupported range format: {r!r}")
        padded_ranges.append(
            pad_single_range(
                start=s,
                end=e,
                video_duration=video_duration,
                padding_before=pad_b,
                padding_after=pad_a,
            )
        )

    merged = merge_overlapping_ranges(padded_ranges)
    return [tr.to_dict() for tr in merged]


def pad_candidate(
    candidate: dict[str, Any],
    video_duration: float,
    padding_seconds: float = DEFAULT_PADDING_SECONDS,
    padding_before: float | None = None,
    padding_after: float | None = None,
) -> dict[str, Any]:
    """Pad ranges for a single candidate dictionary.

    Preserves original candidate ranges unchanged in 'original_ranges',
    and stores the padded, merged ranges in both 'padded_ranges' and 'ranges'.
    """
    cand_copy = copy.deepcopy(candidate)
    original_ranges = cand_copy.get("ranges", [])

    padded_ranges = pad_and_merge_ranges(
        ranges=original_ranges,
        video_duration=video_duration,
        padding_seconds=padding_seconds,
        padding_before=padding_before,
        padding_after=padding_after,
    )

    cand_copy["original_ranges"] = original_ranges
    cand_copy["padded_ranges"] = padded_ranges
    cand_copy["ranges"] = padded_ranges
    cand_copy["original_total_duration_s"] = cand_copy.get("total_duration_s")
    cand_copy["total_duration_s"] = round(
        sum(r["end"] - r["start"] for r in padded_ranges), 2
    )
    return cand_copy


def pad_candidates(
    candidates: list[dict[str, Any]],
    video_duration: float,
    padding_seconds: float = DEFAULT_PADDING_SECONDS,
    padding_before: float | None = None,
    padding_after: float | None = None,
) -> list[dict[str, Any]]:
    """Pad and merge ranges for a list of candidate dictionaries."""
    return [
        pad_candidate(
            cand,
            video_duration=video_duration,
            padding_seconds=padding_seconds,
            padding_before=padding_before,
            padding_after=padding_after,
        )
        for cand in candidates
    ]


def get_video_duration(
    video_dir: Path | str,
    fallback: float = 0.0,
) -> float:
    """Retrieve original video duration from metadata.json or clip_candidates.json."""
    vdir = Path(video_dir)

    metadata_path = vdir / "metadata.json"
    if metadata_path.exists():
        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            if "duration" in meta and meta["duration"] is not None:
                return float(meta["duration"])
        except Exception as exc:
            logger.warning("Could not read duration from %s: %s", metadata_path, exc)

    candidates_path = vdir / "clip_candidates.json"
    if candidates_path.exists():
        try:
            with open(candidates_path, "r", encoding="utf-8") as f:
                cdata = json.load(f)
            if "transcript_duration_s" in cdata:
                return float(cdata["transcript_duration_s"])
        except Exception as exc:
            logger.warning("Could not read duration from %s: %s", candidates_path, exc)

    return fallback


def process_clip_candidates(
    candidates_data: dict[str, Any],
    video_duration: float,
    padding_seconds: float = DEFAULT_PADDING_SECONDS,
    padding_before: float | None = None,
    padding_after: float | None = None,
) -> dict[str, Any]:
    """Process candidates dictionary, adding padded ranges while preserving originals."""
    pad_b = padding_before if padding_before is not None else padding_seconds
    pad_a = padding_after if padding_after is not None else padding_seconds

    out_data = copy.deepcopy(candidates_data)
    candidates = candidates_data.get("candidates", [])
    padded_cands = pad_candidates(
        candidates,
        video_duration=video_duration,
        padding_seconds=padding_seconds,
        padding_before=pad_b,
        padding_after=pad_a,
    )

    out_data["video_duration_s"] = video_duration
    out_data["padding_seconds"] = padding_seconds
    out_data["padding_before_s"] = pad_b
    out_data["padding_after_s"] = pad_a
    out_data["candidates"] = padded_cands
    out_data["candidate_count"] = len(padded_cands)
    return out_data


def run_range_padding(
    video_id: str,
    downloads_dir: Path | str | None = None,
    padding_seconds: float = DEFAULT_PADDING_SECONDS,
    padding_before: float | None = None,
    padding_after: float | None = None,
    video_duration: float | None = None,
    output_filename: str = DEFAULT_OUTPUT_FILENAME,
) -> Path:
    """Execute the range-padding stage for a given video ID.

    Loads ``clip_candidates.json``, applies padding and overlap merging,
    and writes the result to ``output_filename`` (e.g. ``padded_ranges.json``)
    without modifying or overwriting ``clip_candidates.json``.

    Returns the Path to the written padded ranges file.
    """
    base_dir = Path(downloads_dir) if downloads_dir else _DEFAULT_DOWNLOADS_ROOT
    video_dir = base_dir / video_id
    candidates_file = video_dir / "clip_candidates.json"

    if not candidates_file.exists():
        raise FileNotFoundError(f"Clip candidates file not found: {candidates_file}")

    with open(candidates_file, "r", encoding="utf-8") as f:
        candidates_data = json.load(f)

    # Determine original video duration if not explicitly provided
    resolved_duration = (
        float(video_duration)
        if video_duration is not None
        else get_video_duration(video_dir, fallback=candidates_data.get("transcript_duration_s", 0.0))
    )

    result_data = process_clip_candidates(
        candidates_data=candidates_data,
        video_duration=resolved_duration,
        padding_seconds=padding_seconds,
        padding_before=padding_before,
        padding_after=padding_after,
    )

    output_path = video_dir / output_filename
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result_data, f, indent=2)

    return output_path


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} VIDEO_ID")
        sys.exit(1)
    video_id = sys.argv[1]
    run_range_padding(video_id)
