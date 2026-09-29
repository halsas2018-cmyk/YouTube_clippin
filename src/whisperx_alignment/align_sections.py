"""
WhisperX Alignment for extracted video sections.

Pipeline inputs:
  - sections_metadata.json  (section definitions + start_offset per section)
  - section_00N.mp4         (extracted section audio/video files)

Pipeline outputs (written alongside metadata):
  - whisperx_alignment_<section_id>.json   (per-section alignment with local+global timestamps)
  - whisperx_alignment_summary.json        (all sections combined)

Key design decisions:
  - local_start / local_end   = timestamp within the extracted section file (0-based)
  - global_start / global_end = original-video timestamp = local + section.start_offset
  - global timestamps are the authoritative original-video timestamps
  - Never processes the full YouTube video; only operates on the extracted MP4 sections
  - Does NOT call any LLM; WhisperX only
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import warnings
warnings.filterwarnings("ignore")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

WHISPER_MODEL_NAME = "base"          # cached at ~/.cache/huggingface/hub/models--Systran--faster-whisper-base
LANGUAGE = "en"
DEVICE = "cpu"
COMPUTE_TYPE = "float32"             # must be float32 on CPU
BATCH_SIZE = 8


def load_sections_metadata(metadata_path: Path) -> dict[str, Any]:
    """Load and return sections_metadata.json."""
    with open(metadata_path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_whisperx_transcribe(mp4_path: Path, whisper_model: Any) -> list[dict]:
    """
    Run WhisperX ASR transcription on a single MP4 file.
    Returns a list of segment dicts as produced by whisperx.
    """
    import whisperx

    logger.info(f"  Transcribing: {mp4_path.name}")
    audio = whisperx.load_audio(str(mp4_path))
    result = whisper_model.transcribe(audio, batch_size=BATCH_SIZE, language=LANGUAGE)
    return result["segments"]


def run_whisperx_align(
    segments: list[dict],
    mp4_path: Path,
    align_model: Any,
    align_metadata: dict,
) -> list[dict]:
    """
    Run WhisperX forced alignment to get word-level timestamps.
    Returns aligned segments list.
    """
    import whisperx

    audio = whisperx.load_audio(str(mp4_path))
    aligned = whisperx.align(
        segments,
        align_model,
        align_metadata,
        audio,
        DEVICE,
        return_char_alignments=False,
    )
    return aligned["segments"]


def extract_words_with_timestamps(
    aligned_segments: list[dict],
    start_offset: float,
) -> list[dict]:
    """
    Extract per-word timestamps from aligned segments.

    For each word:
      - local_start  / local_end   = timestamp inside the section file (seconds, 0-based)
      - global_start / global_end  = original-video timestamp = local + start_offset

    Returns a flat list of word dicts.
    """
    words: list[dict] = []

    for seg_idx, segment in enumerate(aligned_segments):
        seg_words = segment.get("words", [])
        if not seg_words:
            # Segment has no word-level data — skip (shouldn't happen after alignment)
            logger.warning(
                f"    Segment {seg_idx} has no word-level data: '{segment.get('text', '')}'"
            )
            continue

        for word_entry in seg_words:
            word_text = word_entry.get("word", "").strip()
            local_start = word_entry.get("start")
            local_end = word_entry.get("end")
            score = word_entry.get("score")

            if local_start is None or local_end is None:
                # Some words may not have timing if alignment failed for that token
                logger.warning(f"    Word '{word_text}' missing timestamps; skipping.")
                continue

            # Round to 4 decimal places to avoid floating-point noise
            local_start = round(float(local_start), 4)
            local_end = round(float(local_end), 4)
            global_start = round(local_start + start_offset, 4)
            global_end = round(local_end + start_offset, 4)

            words.append(
                {
                    "word": word_text,
                    "local_start": local_start,
                    "local_end": local_end,
                    "global_start": global_start,
                    "global_end": global_end,
                    "score": round(float(score), 4) if score is not None else None,
                    "segment_index": seg_idx,
                    "segment_text": segment.get("text", "").strip(),
                }
            )

    return words


def build_section_alignment_output(
    section_meta: dict,
    words: list[dict],
    raw_segments: list[dict],
) -> dict:
    """Assemble the full JSON output for one section."""
    start_offset = section_meta["start_offset"]
    return {
        # ── Section metadata (preserved verbatim from extraction output) ──
        "section_id": section_meta["section_id"],
        "candidate_id": section_meta["candidate_id"],
        "video_id": section_meta["video_id"],
        "file_name": section_meta["file_name"],
        "file_path": section_meta["file_path"],
        "start_offset": start_offset,
        "end_offset": section_meta["end_offset"],
        "target_duration_s": section_meta["target_duration_s"],
        "probed_duration_s": section_meta["probed_duration_s"],
        "original_candidate_ranges": section_meta["original_candidate_ranges"],
        "padded_range": section_meta["padded_range"],
        "combined_text": section_meta.get("combined_text"),
        "reason": section_meta.get("reason"),
        # ── Alignment metadata ──
        "alignment": {
            "whisper_model": WHISPER_MODEL_NAME,
            "language": LANGUAGE,
            "device": DEVICE,
            "compute_type": COMPUTE_TYPE,
            "total_words": len(words),
            # NOTE: global timestamps are authoritative original-video timestamps.
            # global_start = local_start + section.start_offset
            # global_end   = local_end   + section.start_offset
            "timestamp_note": (
                "local_start/local_end are relative to the section MP4 file (0-based seconds). "
                "global_start/global_end are authoritative original-video timestamps = "
                "local_timestamp + start_offset."
            ),
        },
        # ── Word-level timestamps ──
        "words": words,
        # ── Raw WhisperX segments (for debugging / future use) ──
        "raw_segments": [
            {
                "start": round(s.get("start", 0.0), 4),
                "end": round(s.get("end", 0.0), 4),
                "text": s.get("text", "").strip(),
            }
            for s in raw_segments
        ],
    }


def align_video_id(video_id: str, sections_dir: Path) -> Path:
    """
    Main alignment routine for a single video_id.

    Reads:   <sections_dir>/sections_metadata.json
             <sections_dir>/section_00N.mp4

    Writes:  <sections_dir>/whisperx_alignment_<section_id>.json  (per-section)
             <sections_dir>/whisperx_alignment_summary.json        (all sections)

    Returns: Path to the summary file.
    """
    import whisperx

    metadata_path = sections_dir / "sections_metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"sections_metadata.json not found: {metadata_path}")

    metadata = load_sections_metadata(metadata_path)
    sections = metadata["sections"]

    logger.info(f"Loading Whisper model '{WHISPER_MODEL_NAME}' on {DEVICE} …")
    whisper_model = whisperx.load_model(
        WHISPER_MODEL_NAME,
        DEVICE,
        compute_type=COMPUTE_TYPE,
        language=LANGUAGE,
    )

    logger.info(f"Loading alignment model for language='{LANGUAGE}' …")
    align_model, align_meta = whisperx.load_align_model(
        language_code=LANGUAGE,
        device=DEVICE,
    )

    all_sections_output: list[dict] = []

    for section in sections:
        section_id = section["section_id"]
        mp4_path = Path(section["file_path"])
        start_offset = float(section["start_offset"])

        logger.info(f"\n{'='*60}")
        logger.info(f"Processing {section_id}  (start_offset={start_offset}s)")
        logger.info(f"  File: {mp4_path}")

        if not mp4_path.exists():
            raise FileNotFoundError(f"Section MP4 not found: {mp4_path}")

        # Step 1: ASR transcription
        raw_segments = run_whisperx_transcribe(mp4_path, whisper_model)
        logger.info(f"  Transcribed {len(raw_segments)} segments.")

        # Step 2: Forced alignment for word-level timestamps
        logger.info(f"  Running forced alignment …")
        aligned_segments = run_whisperx_align(
            raw_segments, mp4_path, align_model, align_meta
        )

        # Step 3: Extract words with local + global timestamps
        words = extract_words_with_timestamps(aligned_segments, start_offset)
        logger.info(f"  Extracted {len(words)} words with timestamps.")

        if words:
            # Log a sample word to show global = local + offset relationship
            sample = words[0]
            logger.info(
                f"  Sample word[0]: '{sample['word']}' "
                f"local=[{sample['local_start']}, {sample['local_end']}]  "
                f"global=[{sample['global_start']}, {sample['global_end']}]  "
                f"(offset={start_offset})"
            )

        # Step 4: Build and write per-section output
        section_output = build_section_alignment_output(section, words, raw_segments)
        out_path = sections_dir / f"whisperx_alignment_{section_id}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(section_output, f, indent=2, ensure_ascii=False)
        logger.info(f"  Written: {out_path}")

        all_sections_output.append(section_output)

    # Step 5: Write summary file
    summary = {
        "video_id": video_id,
        "video_url": metadata.get("video_url", ""),
        "total_sections": len(all_sections_output),
        "alignment_config": {
            "whisper_model": WHISPER_MODEL_NAME,
            "language": LANGUAGE,
            "device": DEVICE,
            "compute_type": COMPUTE_TYPE,
        },
        "timestamp_semantics": {
            "local_start": "seconds from start of extracted section MP4 file (0-based)",
            "local_end": "seconds from start of extracted section MP4 file (0-based)",
            "global_start": "authoritative original-video timestamp = local_start + section.start_offset",
            "global_end": "authoritative original-video timestamp = local_end + section.start_offset",
        },
        "sections": all_sections_output,
    }

    summary_path = sections_dir / "whisperx_alignment_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    logger.info(f"\n{'='*60}")
    logger.info(f"Summary written: {summary_path}")
    return summary_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    video_id = sys.argv[1] if len(sys.argv) > 1 else "FltNsyPXNdo"

    # Derive sections_dir from project layout:
    # src/whisperx_alignment/ → ../../media/downloads/<video_id>/sections/
    this_file = Path(__file__).resolve()
    project_root = this_file.parent.parent.parent   # /root/youtubr_clipper
    sections_dir = project_root / "media" / "downloads" / video_id / "sections"

    logger.info(f"Video ID:     {video_id}")
    logger.info(f"Sections dir: {sections_dir}")

    summary_path = align_video_id(video_id, sections_dir)
    logger.info(f"\nDone. Summary: {summary_path}")
