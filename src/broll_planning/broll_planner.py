"""
B-roll planning stage module.
Reuses llm_client to query the configured LLM for visual treatment decisions
(KEEP_ORIGINAL, USE_BROLL, ORIGINAL_WITH_OVERLAY) per candidate clip,
and maps LLM decisions to authoritative WhisperX word timestamps from final_clip_timings.json/caption_manifest.json.
Enforces at least 50% original video duration per candidate clip.
Creates asset slots ONLY for USE_BROLL and ORIGINAL_WITH_OVERLAY.
"""

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from src.transcript_discovery.llm_client import active_config, chat_json

VALID_DECISIONS = {"KEEP_ORIGINAL", "USE_BROLL", "ORIGINAL_WITH_OVERLAY"}


def normalize_text(text: str) -> str:
    """Normalize text for flexible matching by stripping punctuation and lowering case."""
    return re.sub(r"[^\w\s]", "", text).lower().strip()


def find_phrase_timestamps(
    supported_phrase: str, aligned_words: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """
    Finds contiguous sequence of words matching supported_phrase and returns exact WhisperX timestamps.
    """
    if not supported_phrase or not aligned_words:
        return None

    clean_phrase = normalize_text(supported_phrase)
    phrase_words = clean_phrase.split()
    if not phrase_words:
        return None

    norm_aligned = [normalize_text(w.get("word", "")) for w in aligned_words]

    best_match: Optional[Tuple[int, int]] = None
    max_matched_len = 0

    # Find longest contiguous match starting at any word in norm_aligned
    for i in range(len(norm_aligned)):
        start_p_idx = -1
        for p_idx, pw in enumerate(phrase_words):
            if pw in norm_aligned[i] or norm_aligned[i] in pw:
                start_p_idx = p_idx
                break

        if start_p_idx == -1:
            continue

        p_idx = start_p_idx
        a_idx = i
        while a_idx < len(norm_aligned) and p_idx < len(phrase_words):
            pw = phrase_words[p_idx]
            aw = norm_aligned[a_idx]
            if pw in aw or aw in pw:
                p_idx += 1
                a_idx += 1
            else:
                break

        matched_count = a_idx - i
        if matched_count > max_matched_len:
            max_matched_len = matched_count
            best_match = (i, a_idx - 1)

    # Fallback to single word match if no contiguous block > 0
    if best_match is None:
        phrase_set = set(w for w in phrase_words if len(w) > 2)
        for i, aw in enumerate(norm_aligned):
            if any(pw in aw or aw in pw for pw in phrase_set):
                best_match = (i, i)
                break

    if best_match is None:
        return None

    start_idx, end_idx = best_match
    first_w = aligned_words[start_idx]
    last_w = aligned_words[end_idx]

    return {
        "clip_start": round(first_w["clip_start"], 3),
        "clip_end": round(last_w["clip_end"], 3),
        "duration_s": round(last_w["clip_end"] - first_w["clip_start"], 3),
        "global_start": round(first_w["global_start"], 3),
        "global_end": round(last_w["global_end"], 3),
        "matched_words": [w["word"] for w in aligned_words[start_idx : end_idx + 1]],
        "range_index": first_w.get("range_index", 0),
    }


def compute_broll_duration(all_decisions: List[Dict[str, Any]]) -> float:
    """
    Computes total non-overlapping duration of full-screen USE_BROLL segments.
    """
    intervals = []
    for d in all_decisions:
        if d["decision"] == "USE_BROLL":
            t = d["authoritative_timing"]
            intervals.append((t["clip_start"], t["clip_end"]))

    if not intervals:
        return 0.0

    intervals.sort(key=lambda x: x[0])
    merged = [intervals[0]]
    for current in intervals[1:]:
        prev_start, prev_end = merged[-1]
        if current[0] <= prev_end:
            merged[-1] = (prev_start, max(prev_end, current[1]))
        else:
            merged.append(current)

    return sum(end - start for start, end in merged)


def enforce_original_video_constraint(
    total_clip_duration: float,
    all_decisions: List[Dict[str, Any]],
    asset_slots: List[Dict[str, Any]],
) -> None:
    """
    Enforces that original video is visible for >= 50% of candidate clip duration
    (i.e. full-screen USE_BROLL duration <= 50% of total clip duration).
    Demotes USE_BROLL decisions to ORIGINAL_WITH_OVERLAY if needed.
    """
    if total_clip_duration <= 0:
        return

    max_allowed_broll = 0.50 * total_clip_duration
    current_broll = compute_broll_duration(all_decisions)

    if current_broll <= max_allowed_broll:
        return

    # Demote USE_BROLL decisions to ORIGINAL_WITH_OVERLAY starting with longest
    use_broll_decisions = [d for d in all_decisions if d["decision"] == "USE_BROLL"]
    use_broll_decisions.sort(
        key=lambda d: d["authoritative_timing"]["duration_s"], reverse=True
    )

    for d in use_broll_decisions:
        if compute_broll_duration(all_decisions) <= max_allowed_broll:
            break

        d["decision"] = "ORIGINAL_WITH_OVERLAY"
        phrase = d["supported_phrase"]
        for slot in asset_slots:
            if (
                slot["supported_phrase"] == phrase
                and slot["decision_type"] == "USE_BROLL"
            ):
                slot["decision_type"] = "ORIGINAL_WITH_OVERLAY"
                break


def plan_broll_for_candidate(
    cand: Dict[str, Any], cand_index: int
) -> Dict[str, Any]:
    """
    Sends candidate spoken content to LLM to request visual treatment decisions,
    maps output to WhisperX word timestamps, enforces >=50% original video constraint,
    and generates asset slots for B-roll/overlays.
    """
    cand_id = cand.get("candidate_id", cand_index + 1)
    combined_text = cand.get("combined_text", "")
    aligned_words = cand.get("aligned_words", [])
    total_clip_duration = float(cand.get("total_clip_duration_s", 0.0))

    system_prompt = (
        "You are an expert video editor planning visual track strategy (B-roll vs speaker footage) for a short video clip.\n"
        "Analyze the transcript and break it down into logical visual decisions.\n"
        "Return ONLY a JSON object with a key 'visual_decisions' containing a list of objects.\n"
        "For EACH segment, 'decision' MUST be EXACTLY one of:\n"
        "  - 'KEEP_ORIGINAL': Keep original speaker video.\n"
        "  - 'USE_BROLL': Replace original video with full-screen B-roll stock footage.\n"
        "  - 'ORIGINAL_WITH_OVERLAY': Keep speaker video but overlay a visual graphics/asset.\n\n"
        "Each decision object MUST contain:\n"
        "- 'decision': String ('KEEP_ORIGINAL', 'USE_BROLL', or 'ORIGINAL_WITH_OVERLAY')\n"
        "- 'supported_phrase': The exact sequence of words from the transcript for this decision.\n"
        "- 'purpose': Brief reason for this visual decision.\n\n"
        "For 'USE_BROLL' and 'ORIGINAL_WITH_OVERLAY' ONLY, you MUST ALSO include:\n"
        "- 'visual_concept': Detailed description of the visual asset to display.\n"
        "- 'search_query': Short 2-4 word stock media search query.\n\n"
        "CRITICAL: Do NOT include any timestamps or timing numbers in your response."
    )

    user_prompt = f"Transcript for Candidate Clip #{cand_id}:\n\n\"{combined_text}\""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    response = None
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = chat_json(messages)
            break
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2)
            else:
                print(
                    f"Warning: LLM call failed for candidate {cand_id} after {max_retries} attempts: {e}"
                )
                response = {"visual_decisions": []}

    raw_decisions = []
    if isinstance(response, dict):
        raw_decisions = response.get("visual_decisions", [])
    elif isinstance(response, list):
        raw_decisions = response

    all_decisions = []
    asset_slots = []
    slot_id_counter = 1

    for dec in raw_decisions:
        if not isinstance(dec, dict):
            continue

        decision_type = str(dec.get("decision", "")).strip().upper()
        if decision_type not in VALID_DECISIONS:
            if "BROLL" in decision_type or "B-ROLL" in decision_type:
                decision_type = "USE_BROLL"
            elif "OVERLAY" in decision_type:
                decision_type = "ORIGINAL_WITH_OVERLAY"
            else:
                decision_type = "KEEP_ORIGINAL"

        supported_phrase = str(dec.get("supported_phrase", "")).strip()
        purpose = str(dec.get("purpose", "")).strip()

        if not supported_phrase:
            continue

        timing_info = find_phrase_timestamps(supported_phrase, aligned_words)
        if not timing_info:
            continue

        decision_entry = {
            "decision": decision_type,
            "supported_phrase": supported_phrase,
            "matched_words": timing_info["matched_words"],
            "purpose": purpose,
            "authoritative_timing": {
                "clip_start": timing_info["clip_start"],
                "clip_end": timing_info["clip_end"],
                "duration_s": timing_info["duration_s"],
                "timing_source": "WhisperX word alignment",
            },
            "provenance": {
                "global_start": timing_info["global_start"],
                "global_end": timing_info["global_end"],
            },
        }

        if decision_type in {"USE_BROLL", "ORIGINAL_WITH_OVERLAY"}:
            visual_concept = str(dec.get("visual_concept", "")).strip()
            search_query = str(dec.get("search_query", "")).strip()

            decision_entry["visual_concept"] = visual_concept
            decision_entry["search_query"] = search_query

            slot_id = f"asset_slot_cand_{cand_id}_{slot_id_counter:03d}"
            slot_id_counter += 1

            asset_slots.append(
                {
                    "slot_id": slot_id,
                    "candidate_id": cand_id,
                    "decision_type": decision_type,
                    "supported_phrase": supported_phrase,
                    "matched_words": timing_info["matched_words"],
                    "visual_concept": visual_concept,
                    "search_query": search_query,
                    "purpose": purpose,
                    "authoritative_timing": {
                        "clip_start": timing_info["clip_start"],
                        "clip_end": timing_info["clip_end"],
                        "duration_s": timing_info["duration_s"],
                        "timing_source": "WhisperX word alignment",
                    },
                    "provenance": {
                        "global_start": timing_info["global_start"],
                        "global_end": timing_info["global_end"],
                    },
                }
            )

        all_decisions.append(decision_entry)

    # Enforce >= 50% original video duration constraint
    enforce_original_video_constraint(total_clip_duration, all_decisions, asset_slots)

    # Recalculate decision counts and original video metrics
    counts = {"KEEP_ORIGINAL": 0, "USE_BROLL": 0, "ORIGINAL_WITH_OVERLAY": 0}
    broll_dur = compute_broll_duration(all_decisions)
    orig_video_duration = max(0.0, total_clip_duration - broll_dur)

    for d in all_decisions:
        dt = d["decision"]
        counts[dt] = counts.get(dt, 0) + 1

    orig_video_pct = (
        round((orig_video_duration / total_clip_duration) * 100, 2)
        if total_clip_duration > 0
        else 100.0
    )

    return {
        "candidate_id": cand_id,
        "total_clip_duration_s": total_clip_duration,
        "original_video_duration_s": round(orig_video_duration, 3),
        "broll_duration_s": round(broll_dur, 3),
        "original_video_percentage": orig_video_pct,
        "decision_counts": counts,
        "total_decisions": len(all_decisions),
        "asset_slot_count": len(asset_slots),
        "visual_decisions": all_decisions,
        "asset_slots": asset_slots,
    }


def generate_broll_manifest(media_dir: str) -> str:
    media_path = Path(media_dir)
    timings_file = media_path / "final_clip_timings.json"

    if not timings_file.exists():
        raise FileNotFoundError(f"final_clip_timings.json not found in {media_dir}")

    with open(timings_file, "r") as f:
        timings_data = json.load(f)

    candidates = timings_data.get("candidates", [])
    config_info = active_config()

    candidates_broll = []
    overall_counts = {
        "KEEP_ORIGINAL": 0,
        "USE_BROLL": 0,
        "ORIGINAL_WITH_OVERLAY": 0,
    }
    total_asset_slots = 0
    total_decisions = 0

    for idx, cand in enumerate(candidates):
        cand_broll = plan_broll_for_candidate(cand, idx)
        candidates_broll.append(cand_broll)

        c_counts = cand_broll["decision_counts"]
        for k in overall_counts:
            overall_counts[k] += c_counts.get(k, 0)

        total_decisions += cand_broll["total_decisions"]
        total_asset_slots += cand_broll["asset_slot_count"]

    overall_counts["total_decisions"] = total_decisions

    manifest = {
        "video_id": timings_data.get("video_id"),
        "llm_config": config_info,
        "decision_counts": overall_counts,
        "total_asset_slots": total_asset_slots,
        "candidates": candidates_broll,
    }

    output_path = media_path / "broll_manifest.json"
    with open(output_path, "w") as f:
        json.dump(manifest, f, indent=2)

    return str(output_path)


if __name__ == "__main__":
    import sys

    dir_arg = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "/root/youtubr_clipper/media/downloads/FltNsyPXNdo"
    )
    out_file = generate_broll_manifest(dir_arg)
    print(f"Successfully generated B-roll manifest at: {out_file}")
