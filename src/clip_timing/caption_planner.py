"""
Caption planning stage module.
Consumes word-level timings from final_clip_timings.json and generates caption groups
using clip-relative timestamps as the authoritative rendering timeline.
Preserves original global timestamps as metadata.
"""

import json
from pathlib import Path
from typing import Any, Dict, List


def group_words_into_captions(
    words: List[Dict[str, Any]],
    cand_id: int,
    max_words: int = 4,
    max_duration_s: float = 2.5,
    max_pause_s: float = 0.4,
) -> List[Dict[str, Any]]:
    """
    Groups aligned words into clip-relative caption groups for Remotion rendering.
    """
    if not words:
        return []

    caption_groups = []
    current_group_words = []
    group_counter = 1

    for w in words:
        if not current_group_words:
            current_group_words.append(w)
            continue

        prev_w = current_group_words[-1]

        # Check boundary conditions for starting a new group:
        # 1. Range index change (jump cut)
        range_changed = w.get("range_index") != prev_w.get("range_index")

        # 2. Pause between words exceeds max_pause_s
        pause_exceeded = (w["clip_start"] - prev_w["clip_end"]) > max_pause_s

        # 3. Exceeds max words
        max_words_reached = len(current_group_words) >= max_words

        # 4. Group duration exceeds max_duration_s
        duration_exceeded = (
            w["clip_end"] - current_group_words[0]["clip_start"]
        ) > max_duration_s

        # 5. Punctuation break after previous word (e.g. sentence/clause ending)
        prev_word_text = prev_w.get("word", "")
        punct_break = any(
            prev_word_text.endswith(p) for p in [".", "!", "?", ",", ";", ":"]
        ) and len(current_group_words) >= 2

        if (
            range_changed
            or pause_exceeded
            or max_words_reached
            or duration_exceeded
            or punct_break
        ):
            # Finalize current group
            g_start = round(current_group_words[0]["clip_start"], 3)
            g_end = round(current_group_words[-1]["clip_end"], 3)
            g_duration = round(g_end - g_start, 3)
            group_text = " ".join(item["word"] for item in current_group_words)

            caption_groups.append(
                {
                    "group_id": f"cand_{cand_id}_cap_{group_counter:03d}",
                    "range_index": current_group_words[0].get("range_index", 0),
                    "start_time": g_start,
                    "end_time": g_end,
                    "duration_s": g_duration,
                    "text": group_text,
                    "word_count": len(current_group_words),
                    "words": [
                        {
                            "word": item["word"],
                            "clip_start": round(item["clip_start"], 3),
                            "clip_end": round(item["clip_end"], 3),
                            "global_start": round(item["global_start"], 3),
                            "global_end": round(item["global_end"], 3),
                            "score": item.get("score"),
                        }
                        for item in current_group_words
                    ],
                }
            )
            group_counter += 1
            current_group_words = [w]
        else:
            current_group_words.append(w)

    # Flush last group
    if current_group_words:
        g_start = round(current_group_words[0]["clip_start"], 3)
        g_end = round(current_group_words[-1]["clip_end"], 3)
        g_duration = round(g_end - g_start, 3)
        group_text = " ".join(item["word"] for item in current_group_words)

        caption_groups.append(
            {
                "group_id": f"cand_{cand_id}_cap_{group_counter:03d}",
                "range_index": current_group_words[0].get("range_index", 0),
                "start_time": g_start,
                "end_time": g_end,
                "duration_s": g_duration,
                "text": group_text,
                "word_count": len(current_group_words),
                "words": [
                    {
                        "word": item["word"],
                        "clip_start": round(item["clip_start"], 3),
                        "clip_end": round(item["clip_end"], 3),
                        "global_start": round(item["global_start"], 3),
                        "global_end": round(item["global_end"], 3),
                        "score": item.get("score"),
                    }
                    for item in current_group_words
                ],
            }
        )

    return caption_groups


def generate_caption_manifest(media_dir: str) -> str:
    """
    Consumes final_clip_timings.json from media_dir and outputs caption_manifest.json.
    """
    media_path = Path(media_dir)
    timings_file = media_path / "final_clip_timings.json"

    if not timings_file.exists():
        raise FileNotFoundError(f"final_clip_timings.json not found in {media_dir}")

    with open(timings_file, "r") as f:
        timings_data = json.load(f)

    candidates_captions = []

    for cand in timings_data.get("candidates", []):
        cand_id = cand.get("candidate_id")
        aligned_words = cand.get("aligned_words", [])
        caption_groups = group_words_into_captions(aligned_words, cand_id)

        candidates_captions.append(
            {
                "candidate_id": cand_id,
                "total_clip_duration_s": cand.get("total_clip_duration_s"),
                "caption_group_count": len(caption_groups),
                "caption_groups": caption_groups,
            }
        )

    output_manifest = {
        "video_id": timings_data.get("video_id"),
        "llm_provider": timings_data.get("llm_provider"),
        "llm_model": timings_data.get("llm_model"),
        "candidates": candidates_captions,
    }

    output_file = media_path / "caption_manifest.json"
    with open(output_file, "w") as f:
        json.dump(output_manifest, f, indent=2)

    return str(output_file)


if __name__ == "__main__":
    import sys

    dir_arg = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "/root/youtubr_clipper/media/downloads/FltNsyPXNdo"
    )
    out_file = generate_caption_manifest(dir_arg)
    print(f"Successfully generated caption manifest at: {out_file}")
