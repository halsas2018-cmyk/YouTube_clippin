"""
Clip timing stage module.
Uses WhisperX global word timestamps to map candidate speech ranges to authoritative global and clip-relative timing.
"""

import json
import os
from pathlib import Path


def process_clip_timing(media_dir: str):
    """
    Process clip candidates and WhisperX alignment for a video directory to compute global and clip-relative timings.
    """
    media_path = Path(media_dir)
    candidates_file = media_path / "clip_candidates.json"
    padded_file = media_path / "padded_ranges.json"
    summary_file = media_path / "sections" / "whisperx_alignment_summary.json"

    if not candidates_file.exists():
        raise FileNotFoundError(f"Clip candidates file not found: {candidates_file}")
    if not padded_file.exists():
        raise FileNotFoundError(f"Padded ranges file not found: {padded_file}")
    if not summary_file.exists():
        raise FileNotFoundError(f"WhisperX alignment summary file not found: {summary_file}")

    with open(candidates_file, "r") as f:
        candidates_data = json.load(f)
    with open(padded_file, "r") as f:
        padded_data = json.load(f)
    with open(summary_file, "r") as f:
        summary_data = json.load(f)

    # Build section lookup by candidate_id
    sections_by_candidate = {}
    for section in summary_data.get("sections", []):
        cand_id = section.get("candidate_id")
        sections_by_candidate[cand_id] = section

    output_candidates = []

    for idx, cand in enumerate(candidates_data.get("candidates", [])):
        cand_id = idx + 1
        section = sections_by_candidate.get(cand_id, {})
        section_words = section.get("words", [])
        padded_cand = (
            padded_data.get("candidates", [])[idx]
            if idx < len(padded_data.get("candidates", []))
            else {}
        )

        orig_ranges = cand.get("ranges", [])
        selected_global_ranges = []
        clip_relative_ranges = []
        all_aligned_words = []
        current_clip_time = 0.0

        for r_idx, r in enumerate(orig_ranges):
            target_start = r["start"]
            target_end = r["end"]

            # Find overlapping words for target range
            matched_words = [
                w
                for w in section_words
                if w.get("global_end", 0.0) > target_start
                and w.get("global_start", 0.0) < target_end
            ]

            if not matched_words:
                # Fallback if no exact overlapping word, find closest words
                matched_words = [
                    w
                    for w in section_words
                    if abs(w.get("global_start", 0.0) - target_start) < 1.0
                    or abs(w.get("global_end", 0.0) - target_end) < 1.0
                ]

            if matched_words:
                # Ensure final boundaries do not cut through a word
                g_start = round(matched_words[0]["global_start"], 3)
                g_end = round(matched_words[-1]["global_end"], 3)
                duration = round(g_end - g_start, 3)

                c_start = round(current_clip_time, 3)
                c_end = round(c_start + duration, 3)

                global_range_obj = {
                    "range_index": r_idx,
                    "target_start": target_start,
                    "target_end": target_end,
                    "global_start": g_start,
                    "global_end": g_end,
                    "duration_s": duration,
                    "first_word": matched_words[0].get("word"),
                    "last_word": matched_words[-1].get("word"),
                    "word_count": len(matched_words),
                }
                selected_global_ranges.append(global_range_obj)

                clip_range_obj = {
                    "range_index": r_idx,
                    "clip_start": c_start,
                    "clip_end": c_end,
                    "duration_s": duration,
                    "global_start": g_start,
                    "global_end": g_end,
                }
                clip_relative_ranges.append(clip_range_obj)

                for w in matched_words:
                    w_g_start = round(w["global_start"], 3)
                    w_g_end = round(w["global_end"], 3)
                    w_c_start = round(c_start + (w_g_start - g_start), 3)
                    w_c_end = round(c_start + (w_g_end - g_start), 3)

                    all_aligned_words.append(
                        {
                            "word": w.get("word"),
                            "global_start": w_g_start,
                            "global_end": w_g_end,
                            "clip_start": w_c_start,
                            "clip_end": w_c_end,
                            "score": w.get("score"),
                            "range_index": r_idx,
                        }
                    )

                current_clip_time = c_end

        output_candidates.append(
            {
                "candidate_id": cand_id,
                "reason": cand.get("reason"),
                "cut_description": cand.get("cut_description"),
                "combined_text": cand.get("combined_text"),
                "original_candidate_ranges": orig_ranges,
                "padded_ranges": padded_cand.get("padded_ranges", []),
                "selected_global_ranges": selected_global_ranges,
                "clip_relative_ranges": clip_relative_ranges,
                "total_clip_duration_s": round(current_clip_time, 3),
                "aligned_words": all_aligned_words,
            }
        )

    output_data = {
        "video_id": candidates_data.get("video_id"),
        "llm_provider": candidates_data.get("llm_provider"),
        "llm_model": candidates_data.get("llm_model"),
        "candidate_count": len(output_candidates),
        "candidates": output_candidates,
    }

    output_path = media_path / "final_clip_timings.json"
    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2)

    return output_path, output_data


if __name__ == "__main__":
    import sys

    dir_arg = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "/root/youtubr_clipper/media/downloads/FltNsyPXNdo"
    )
    out_path, data = process_clip_timing(dir_arg)
    print(f"Successfully generated clip timing at: {out_path}")
