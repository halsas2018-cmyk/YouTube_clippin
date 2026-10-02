"""Media extraction for section ranges using yt-dlp, ffmpeg, and ffprobe.

Downloads and extracts only the padded ranges for candidate clips, preserving
the original-video start offsets in metadata so downstream stages (e.g. WhisperX)
can shift timestamps back to original-video coordinates.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DOWNLOADS_ROOT = _PROJECT_ROOT / "media" / "downloads"
_VENV_YTDLP = Path("/root/kinetic_typo_vid/venv/bin/yt-dlp")


def get_ytdlp_binary() -> str:
    """Find the yt-dlp binary, preferring the designated venv."""
    if _VENV_YTDLP.exists() and os.access(_VENV_YTDLP, os.X_OK):
        return str(_VENV_YTDLP)
    system_ytdlp = shutil.which("yt-dlp")
    if system_ytdlp:
        return system_ytdlp
    raise FileNotFoundError("yt-dlp executable not found in venv or system PATH.")


def probe_media_info(file_path: Path | str) -> dict[str, Any]:
    """Probe detailed stream and format information using ffprobe."""
    fpath = Path(file_path)
    if not fpath.exists():
        raise FileNotFoundError(f"Media file not found for ffprobe: {fpath}")

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration,size,bit_rate:stream=index,codec_name,codec_type,width,height,duration",
        "-of",
        "json",
        str(fpath),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def probe_media_duration(file_path: Path | str) -> float:
    """Probe exact container duration using ffprobe."""
    fpath = Path(file_path)
    if not fpath.exists():
        raise FileNotFoundError(f"Media file not found for ffprobe: {fpath}")

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(fpath),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    val = res.stdout.strip()
    return round(float(val), 3) if val else 0.0


def is_valid_media_file(file_path: Path | str, require_video: bool = True) -> bool:
    """Check if the media file exists and can be probed by ffprobe without errors."""
    fpath = Path(file_path)
    if not fpath.exists() or fpath.stat().st_size == 0:
        return False
    try:
        duration = probe_media_duration(fpath)
        if duration <= 0.0:
            return False
        if require_video:
            info = probe_media_info(fpath)
            streams = info.get("streams", [])
            if not any(s.get("codec_type") == "video" for s in streams):
                return False
        return True
    except Exception:
        return False


@dataclass
class SectionMetadata:
    """Metadata for an extracted video section."""

    section_id: str
    candidate_id: int
    video_id: str
    file_name: str
    file_path: str
    start_offset: float
    end_offset: float
    target_duration_s: float
    probed_duration_s: float
    original_candidate_ranges: list[dict[str, float]]
    padded_range: dict[str, float]
    streams: list[dict[str, Any]] = field(default_factory=list)
    combined_text: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def download_section_range(
    video_url: str,
    start_time: float,
    end_time: float,
    output_path: Path | str,
    format_spec: str = "bestvideo[protocol^=https]+bestaudio[protocol^=https]/bestvideo+bestaudio/bestvideo",
    ytdlp_bin: str | None = None,
    overwrite: bool = False,
    max_retries: int = 2,
) -> Path:
    """Download only the specified section range using yt-dlp and ffmpeg.

    Tries MP4 format first, falls back to best available video if MP4 not available.
    Merges to MP4 container. Does NOT download the entire video. Validates file integrity with ffprobe.
    """
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    if out_file.exists() and not overwrite and is_valid_media_file(out_file, require_video=True):
        logger.info("Valid output file %s already exists, skipping download.", out_file)
        return out_file

    binary = ytdlp_bin or get_ytdlp_binary()
    section_arg = f"*{start_time:.2f}-{end_time:.2f}"
    outtmpl = str(out_file.with_suffix("")) + ".%(ext)s"

    # Try MP4 first, then fallback to best available video merged into MP4
    format_specs = [
        format_spec,
        "bestvideo+bestaudio/bestvideo",
    ]

    last_error: Exception | None = None
    for fmt_idx, fmt in enumerate(format_specs):
        cmd = [
            binary,
            "--download-sections",
            section_arg,
            "-f",
            fmt,
            "--merge-output-format",
            "mp4",
            "-o",
            outtmpl,
            "--force-overwrites",
            "--no-warnings",
            video_url,
        ]

        for attempt in range(1, max_retries + 1):
            # Remove partial files before attempting
            for part_file in out_file.parent.glob(f"{out_file.stem}.*part"):
                try:
                    part_file.unlink(missing_ok=True)
                except Exception:
                    pass

            logger.info(
                "Executing section download (format %d/%d, attempt %d/%d): %s",
                fmt_idx + 1,
                len(format_specs),
                attempt,
                max_retries,
                " ".join(cmd),
            )
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                last_error = RuntimeError(
                    f"yt-dlp failed (code {res.returncode}): {res.stderr or res.stdout}"
                )
                continue

            # Locate output file
            actual_file: Path | None = None
            if out_file.exists():
                actual_file = out_file
            else:
                candidates = list(out_file.parent.glob(f"{out_file.stem}.*"))
                for cand in candidates:
                    if cand.suffix in (".mp4", ".mkv", ".webm") and not cand.name.endswith(".part"):
                        actual_file = cand
                        break

            if actual_file and is_valid_media_file(actual_file):
                logger.info("Successfully downloaded with format: %s", actual_file.suffix)
                return actual_file

            last_error = RuntimeError(
                f"Downloaded file at {actual_file or out_file} failed ffprobe integrity check."
            )
            if actual_file and actual_file.exists():
                try:
                    actual_file.unlink(missing_ok=True)
                except Exception:
                    pass

    raise last_error or RuntimeError(f"Failed to download section range [{start_time} - {end_time}]")


def extract_sections(
    video_id: str,
    downloads_dir: Path | str | None = None,
    padded_ranges_filename: str = "padded_ranges.json",
    sections_subdir: str = "sections",
    overwrite: bool = False,
) -> list[SectionMetadata]:
    """Extract all padded ranges for the given video ID.

    Reads ``padded_ranges.json``, downloads only the padded ranges into
    ``media/downloads/{video_id}/sections/``, probes their actual durations with
    ffprobe, and writes metadata with original-video start offsets.
    """
    base_dir = Path(downloads_dir) if downloads_dir else _DEFAULT_DOWNLOADS_ROOT
    video_dir = base_dir / video_id
    padded_file = video_dir / padded_ranges_filename

    if not padded_file.exists():
        raise FileNotFoundError(f"Padded ranges file not found: {padded_file}")

    with open(padded_file, "r", encoding="utf-8") as f:
        padded_data = json.load(f)

    # Determine video URL from metadata.json if available
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    meta_path = video_dir / "metadata.json"
    if meta_path.exists():
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            if "webpage_url" in meta and meta["webpage_url"]:
                video_url = meta["webpage_url"]
        except Exception as exc:
            logger.warning("Could not read webpage_url from %s: %s", meta_path, exc)

    sections_dir = video_dir / sections_subdir
    sections_dir.mkdir(parents=True, exist_ok=True)

    extracted_sections: list[SectionMetadata] = []
    section_counter = 1

    for cand_idx, candidate in enumerate(padded_data.get("candidates", []), start=1):
        original_ranges = candidate.get("original_ranges", candidate.get("ranges", []))
        padded_ranges = candidate.get("padded_ranges", candidate.get("ranges", []))
        combined_text = candidate.get("combined_text", "")
        reason = candidate.get("reason", "")

        for r_idx, pr in enumerate(padded_ranges, start=1):
            start_offset = float(pr["start"])
            end_offset = float(pr["end"])
            target_duration = round(end_offset - start_offset, 2)

            section_id = f"section_{section_counter:03d}"
            target_media_file = sections_dir / f"{section_id}.mp4"

            # Download only the padded range
            actual_media_file = download_section_range(
                video_url=video_url,
                start_time=start_offset,
                end_time=end_offset,
                output_path=target_media_file,
                overwrite=overwrite,
            )

            # Probe exact duration and streams with ffprobe
            probe_info = probe_media_info(actual_media_file)
            format_info = probe_info.get("format", {})
            probed_duration = round(float(format_info.get("duration", target_duration)), 3)
            streams_info = [
                {
                    "index": s.get("index"),
                    "codec_name": s.get("codec_name"),
                    "codec_type": s.get("codec_type"),
                    "duration": s.get("duration"),
                }
                for s in probe_info.get("streams", [])
            ]

            sec_meta = SectionMetadata(
                section_id=section_id,
                candidate_id=cand_idx,
                video_id=video_id,
                file_name=actual_media_file.name,
                file_path=str(actual_media_file),
                start_offset=start_offset,
                end_offset=end_offset,
                target_duration_s=target_duration,
                probed_duration_s=probed_duration,
                original_candidate_ranges=original_ranges,
                padded_range=pr,
                streams=streams_info,
                combined_text=combined_text,
                reason=reason,
            )

            # Save per-section sidecar metadata
            sidecar_path = sections_dir / f"{section_id}.json"
            with open(sidecar_path, "w", encoding="utf-8") as f:
                json.dump(sec_meta.to_dict(), f, indent=2)

            extracted_sections.append(sec_meta)
            section_counter += 1

    # Save overall sections manifest
    manifest_data = {
        "video_id": video_id,
        "video_url": video_url,
        "total_sections": len(extracted_sections),
        "sections": [s.to_dict() for s in extracted_sections],
    }
    manifest_path = sections_dir / "sections_metadata.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)

    return extracted_sections
