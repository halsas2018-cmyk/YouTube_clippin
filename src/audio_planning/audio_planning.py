#!/usr/bin/env python3
"""
Stage 11 — LLM-driven audio planning.

Reads clip context (transcript, caption groups, broll decisions, aligned words)
and asks the LLM to produce a creative audio plan: music mood/search-query,
per-segment SFX style, and ducking decisions.

The output is an ``audio_planning_manifest_cand{N}.json`` file in the same
format as before, so Stage 12 (mix_audio.py) and Remotion are unaffected.
"""
import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def load_json(path: str) -> dict:
    with open(path, "r") as f:
        return json.load(f)


def save_json(data: dict, path: str) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# LLM client (re-use the existing shared client)
# ---------------------------------------------------------------------------

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.transcript_discovery.llm_client import chat_json, active_config  # noqa: E402


# ---------------------------------------------------------------------------
# Build the LLM prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an expert video editor specialising in short-form social-media clips.
Given a clip's transcript, caption groups and b-roll decisions, produce a JSON
audio plan that will make the clip engaging and punchy.

Return ONLY a JSON object — no markdown fences, no explanations.

Schema:
{
  "music_mood": "<one short phrase describing the vibe, e.g. 'upbeat tech-focused'>",
  "music_search_query": "<2–5 word search query to find background music on Freesound, e.g. 'upbeat corporate tech background'>",
  "sfx_search_queries": {
    "whoosh": "<2–4 word search query for a whoosh/swoosh SFX>",
    "click": "<2–4 word search query for a UI click SFX>"
  },
  "background_music_volume": <float 0.1–0.5, how loud the background music should be overall>,
  "speech_ducking": [
    {"start": <float seconds>, "end": <float seconds>, "duck_amount": <float 0.4–0.9>}
  ],
  "sfx": [
    {"time": <float seconds>, "type": "<whoosh_in|whoosh_out|click>", "volume": <float 0.1–0.6>, "description": "<brief reason>"}
  ]
}

Rules:
- Include a ducking entry for EVERY caption group (speech region).
- Duck amount 0.7 = reduce music 70 % during that region. Use higher duck (0.8–0.9) for
  emotional/punchline moments, lower (0.5–0.6) for sections where music adds energy.
- Place whoosh_in at the START of each b-roll decision, whoosh_out at the END.
- Place a click SFX only on truly impactful words (score ≥ 0.92), max 6 clicks total.
- Keep sfx volume between 0.2 and 0.6.
- All times must be within [0, total_duration_s].
"""


def build_user_message(
    combined_text: str,
    total_duration: float,
    caption_groups: list,
    visual_decisions: list,
    aligned_words: list,
    music_mood_hint: str = "",
) -> str:
    # Summarise aligned words: only high-score ones, trim for prompt length
    high_score_words = [
        {"word": w["word"], "clip_start": round(w["clip_start"], 3), "score": round(w["score"], 2)}
        for w in aligned_words
        if w.get("score", 0) >= 0.90
    ][:20]  # cap at 20 to keep prompt concise

    # Summarise visual decisions
    vd_summary = [
        {
            "decision": vd["decision"],
            "phrase": vd.get("supported_phrase", "")[:60],
            "clip_start": round(vd["authoritative_timing"]["clip_start"], 3),
            "clip_end": round(vd["authoritative_timing"]["clip_end"], 3),
        }
        for vd in visual_decisions
    ]

    # Caption groups summary
    cg_summary = [
        {
            "text": cg["text"][:80],
            "start": round(cg["start_time"], 3),
            "end": round(cg["end_time"], 3),
        }
        for cg in caption_groups
    ]

    payload = {
        "clip_transcript": combined_text,
        "total_duration_s": round(total_duration, 3),
        "mood_hint": music_mood_hint or "infer from transcript",
        "caption_groups": cg_summary,
        "visual_decisions": vd_summary,
        "high_score_words": high_score_words,
    }
    return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Validate LLM output
# ---------------------------------------------------------------------------

def validate_plan(plan: dict, total_duration: float) -> list[str]:
    """Return list of error strings; empty = valid."""
    errors: list[str] = []

    required_keys = {
        "music_mood", "music_search_query", "sfx_search_queries",
        "background_music_volume", "speech_ducking", "sfx",
    }
    for k in required_keys:
        if k not in plan:
            errors.append(f"Missing key: {k}")

    if "speech_ducking" in plan:
        for i, d in enumerate(plan["speech_ducking"]):
            for fld in ("start", "end", "duck_amount"):
                if fld not in d:
                    errors.append(f"speech_ducking[{i}] missing {fld}")
                    continue
            if d.get("end", 0) > total_duration + 0.1:
                errors.append(f"speech_ducking[{i}] end {d['end']} > total_duration {total_duration}")

    if "sfx" in plan:
        for i, e in enumerate(plan["sfx"]):
            for fld in ("time", "type", "volume"):
                if fld not in e:
                    errors.append(f"sfx[{i}] missing {fld}")
            if e.get("type") not in ("whoosh_in", "whoosh_out", "click", None):
                errors.append(f"sfx[{i}] unknown type {e.get('type')}")
            if e.get("time", 0) > total_duration + 0.1:
                errors.append(f"sfx[{i}] time {e.get('time')} > total_duration {total_duration}")

    return errors


# ---------------------------------------------------------------------------
# Convert LLM plan → manifest (add legacy fields expected by mix_audio.py)
# ---------------------------------------------------------------------------

def plan_to_manifest(plan: dict, video_id: str, candidate_id: int, total_duration: float) -> dict:
    bg_vol = float(plan.get("background_music_volume", 0.3))
    bg_vol = max(0.1, min(0.5, bg_vol))

    return {
        "video_id": video_id,
        "selected_candidate_id": candidate_id,
        "total_clip_duration_s": total_duration,
        # LLM creative choices (stored for acquisition stage)
        "music_mood": plan.get("music_mood", ""),
        "music_search_query": plan.get("music_search_query", "background music"),
        "sfx_search_queries": plan.get("sfx_search_queries", {
            "whoosh": "whoosh swoosh",
            "click": "ui click",
        }),
        # Mix parameters
        "background_music": [
            {
                "start": 0.0,
                "end": total_duration,
                "volume": bg_vol,
                "ducking": True,
            }
        ],
        "speech_ducking": plan.get("speech_ducking", []),
        "sfx": plan.get("sfx", []),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # --- Argument parsing ---
    if len(sys.argv) < 2 or len(sys.argv) > 4:
        print(f"Usage: {sys.argv[0]} VIDEO_ID [--candidate-id N]")
        sys.exit(1)
    video_id = sys.argv[1]
    candidate_id = 1
    if len(sys.argv) == 4:
        if sys.argv[2] == "--candidate-id":
            try:
                candidate_id = int(sys.argv[3])
            except ValueError:
                print("Error: --candidate-id must be an integer")
                sys.exit(1)
        else:
            print(f"Usage: {sys.argv[0]} VIDEO_ID [--candidate-id N]")
            sys.exit(1)
    elif len(sys.argv) == 3:
        print(f"Usage: {sys.argv[0]} VIDEO_ID [--candidate-id N]")
        sys.exit(1)

    base_dir = f"/root/youtubr_clipper/media/downloads/{video_id}"

    # --- Load data ---
    final_clip_timings = load_json(os.path.join(base_dir, "final_clip_timings.json"))
    caption_manifest = load_json(os.path.join(base_dir, "caption_manifest.json"))
    broll_manifest = load_json(os.path.join(base_dir, "broll_manifest.json"))

    # Locate selected candidate data
    cand_data = next(
        (c for c in final_clip_timings["candidates"] if c["candidate_id"] == candidate_id),
        None,
    )
    if cand_data is None:
        raise ValueError(f"Candidate {candidate_id} not found in final_clip_timings.json")

    total_duration: float = cand_data["total_clip_duration_s"]
    combined_text: str = cand_data.get("combined_text", "")
    aligned_words: list = cand_data.get("aligned_words", [])

    caption_groups = next(
        (c["caption_groups"] for c in caption_manifest["candidates"] if c["candidate_id"] == candidate_id),
        None,
    )
    if caption_groups is None:
        raise ValueError(f"Caption groups for candidate {candidate_id} not found")

    broll_data = next(
        (c for c in broll_manifest["candidates"] if c["candidate_id"] == candidate_id),
        None,
    )
    if broll_data is None:
        raise ValueError(f"Broll data for candidate {candidate_id} not found")
    visual_decisions: list = broll_data.get("visual_decisions", [])

    # --- Call LLM ---
    cfg = active_config()
    print(f"Calling LLM ({cfg['provider']}/{cfg['model']}) for audio planning …")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_message(
            combined_text=combined_text,
            total_duration=total_duration,
            caption_groups=caption_groups,
            visual_decisions=visual_decisions,
            aligned_words=aligned_words,
        )},
    ]

    plan = chat_json(messages, temperature=0.4, max_tokens=4096)

    # --- Validate ---
    errors = validate_plan(plan, total_duration)
    if errors:
        print("⚠ LLM plan has issues — falling back to rule-based defaults for bad fields:")
        for e in errors:
            print(f"  - {e}")
        # Patch missing / bad speech_ducking with caption groups
        if "speech_ducking" not in plan or errors:
            plan.setdefault("speech_ducking", [
                {"start": cg["start_time"], "end": cg["end_time"], "duck_amount": 0.7}
                for cg in caption_groups
            ])

    # --- Convert to manifest ---
    manifest = plan_to_manifest(plan, video_id, candidate_id, total_duration)

    # --- Save ---
    output_path = os.path.join(base_dir, f"audio_planning_manifest_cand{candidate_id}.json")
    save_json(manifest, output_path)

    print(f"\n✓ Audio planning manifest written to {output_path}")
    print(f"  Music mood       : {manifest['music_mood']}")
    print(f"  Music query      : {manifest['music_search_query']}")
    print(f"  SFX queries      : {manifest['sfx_search_queries']}")
    print(f"  BG music volume  : {manifest['background_music'][0]['volume']}")
    print(f"  Speech ducking   : {len(manifest['speech_ducking'])} regions")
    print(f"  SFX events       : {len(manifest['sfx'])}")


if __name__ == "__main__":
    main()