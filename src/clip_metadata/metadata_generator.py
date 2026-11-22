#!/usr/bin/env python3
"""
Clip metadata generator (Title, Description, Hashtags, Tags).

Calls the configured LLM with the full transcript and context of each candidate clip
to produce engaging, platform-optimized titles, descriptions, and hashtags.

Outputs:
  - clip_cand{cand_id}_metadata.json: structured JSON for automation
  - clip_cand{cand_id}_info.txt: human-readable text for direct copy-pasting
  - clip_metadata_manifest.json: unified manifest containing all candidate metadata
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add the project root to sys.path so we can import src modules
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.transcript_discovery.llm_client import active_config, chat_json


def resolve_video_dir(target: str, project_root: Path = PROJECT_ROOT) -> tuple[str, Path]:
    """Resolve video_id and directory path from target (video ID or directory path)."""
    p = Path(target)
    if p.exists() and p.is_dir():
        video_id = p.name
        return video_id, p

    video_id = target
    # Check default download locations
    candidate_paths = [
        project_root / "media" / "downloads" / video_id,
        project_root / "remotion" / "public" / "media" / "downloads" / video_id,
    ]
    for cp in candidate_paths:
        if cp.exists() and cp.is_dir():
            return video_id, cp

    # Default to media/downloads/<video_id>
    default_path = project_root / "media" / "downloads" / video_id
    default_path.mkdir(parents=True, exist_ok=True)
    return video_id, default_path


def load_source_video_metadata(work_dir: Path) -> dict[str, Any]:
    """Attempt to load source video metadata (title, channel, url) if available."""
    metadata_candidates = [
        work_dir / "metadata.json",
        work_dir / "sections" / "sections_metadata.json",
    ]
    for meta_file in metadata_candidates:
        if meta_file.exists():
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if "title" in data:
                    return data
                if "video_url" in data:
                    return {"webpage_url": data["video_url"]}
            except Exception:
                pass
    return {}


def build_metadata_prompt(
    combined_text: str,
    cand_id: int,
    duration_s: float,
    reason: str,
    original_title: str = "",
) -> list[dict[str, str]]:
    """Build the LLM prompt for generating clip title, description, and hashtags."""
    system_prompt = (
        "You are an expert viral video copywriter and social media strategist for short-form platforms "
        "(YouTube Shorts, TikTok, Instagram Reels).\n"
        "Your task is to craft high-performing, high-CTR titles, compelling descriptions, and targeted hashtags "
        "based on the complete spoken transcript of a video clip.\n\n"
        "Guidelines:\n"
        "1. Title:\n"
        "   - Maximum 60 characters.\n"
        "   - Punchy, curiosity-piquing, bold, or question-based.\n"
        "   - Do NOT use generic titles like 'Clip 1' or 'Great Advice'. Make it specific to the content.\n"
        "2. Description:\n"
        "   - 2 to 4 engaging sentences.\n"
        "   - Summarize the key takeaway or provocative hook.\n"
        "   - Include a clear call-to-action (CTA) to encourage comments or shares.\n"
        "3. Hashtags:\n"
        "   - 4 to 8 relevant hashtags, starting with #Shorts followed by niche and topic tags.\n"
        "4. Tags:\n"
        "   - 5 to 10 SEO search tags (without the '#' symbol) for discovery.\n\n"
        "Return ONLY a valid JSON object matching this exact schema:\n"
        "{\n"
        '  "title": "Short punchy title under 60 chars",\n'
        '  "description": "Engaging description with key takeaway and CTA",\n'
        '  "hashtags": ["#Shorts", "#Tag1", "#Tag2"],\n'
        '  "tags": ["tag1", "tag2", "tag3"]\n'
        "}"
    )

    user_prompt = (
        f"Clip Details:\n"
        f"- Candidate ID: {cand_id}\n"
        f"- Duration: {duration_s:.1f} seconds\n"
    )
    if original_title:
        user_prompt += f"- Source Video Title: {original_title}\n"
    if reason:
        user_prompt += f"- Hook / Context: {reason}\n"

    user_prompt += (
        f"\nFull Spoken Transcript of the Clip:\n"
        f'"{combined_text}"\n\n'
        f"Generate the title, description, hashtags, and tags now."
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def generate_for_candidate(
    cand: dict[str, Any],
    original_title: str,
    max_retries: int = 3,
) -> dict[str, Any]:
    """Call LLM to generate metadata for a single candidate clip."""
    cand_id = cand.get("candidate_id", 1)
    combined_text = cand.get("combined_text", "").strip()
    duration_s = float(cand.get("total_clip_duration_s", 0.0))
    reason = cand.get("reason", "")

    if not combined_text:
        print(f"  [Cand {cand_id}] Warning: No combined_text found. Using fallback.")
        return {
            "title": f"Clip {cand_id}",
            "description": reason or "Check out this clip!",
            "hashtags": ["#Shorts"],
            "tags": ["shorts"],
        }

    messages = build_metadata_prompt(
        combined_text=combined_text,
        cand_id=cand_id,
        duration_s=duration_s,
        reason=reason,
        original_title=original_title,
    )

    response = None
    for attempt in range(max_retries):
        try:
            response = chat_json(messages)
            if isinstance(response, dict) and "title" in response and "description" in response:
                break
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"  [Cand {cand_id}] LLM attempt {attempt + 1} failed ({e}), retrying...")
                time.sleep(2)
            else:
                print(f"  [Cand {cand_id}] Warning: LLM call failed after {max_retries} attempts: {e}")

    # Process response or use fallback
    if isinstance(response, dict) and "title" in response:
        title = str(response.get("title", "")).strip()
        description = str(response.get("description", "")).strip()
        hashtags = response.get("hashtags", [])
        if not isinstance(hashtags, list):
            hashtags = [str(hashtags)]
        hashtags = [h if h.startswith("#") else f"#{h}" for h in hashtags]
        if "#Shorts" not in hashtags and "#shorts" not in hashtags:
            hashtags.insert(0, "#Shorts")

        tags = response.get("tags", [])
        if not isinstance(tags, list):
            tags = [str(tags)]
        tags = [str(t).lstrip("#").strip() for t in tags if str(t).strip()]

        return {
            "title": title,
            "description": description,
            "hashtags": hashtags,
            "tags": tags,
        }

    # Fallback
    fallback_title = combined_text[:50].strip() + "..."
    return {
        "title": fallback_title,
        "description": reason or combined_text[:150],
        "hashtags": ["#Shorts"],
        "tags": ["shorts"],
    }


def generate_clip_metadata(
    target: str,
    project_root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    """
    Main entry point for generating title, description, and hashtags for all clips.
    """
    video_id, work_dir = resolve_video_dir(target, project_root)
    print(f"\nGenerating clip metadata for video: {video_id}")
    print(f"Working directory: {work_dir}")
    print(f"LLM Configuration: {active_config()}")

    # 1. Load timings / candidates
    timings_path = work_dir / "final_clip_timings.json"
    if not timings_path.exists():
        # Fallback check
        alt_path = project_root / "remotion" / "public" / "media" / "downloads" / video_id / "final_clip_timings.json"
        if alt_path.exists():
            timings_path = alt_path

    if not timings_path.exists():
        raise FileNotFoundError(f"Could not find final_clip_timings.json for {video_id} in {work_dir}")

    with open(timings_path, "r", encoding="utf-8") as f:
        timings_data = json.load(f)

    candidates = timings_data.get("candidates", [])
    if not candidates:
        print("No candidates found in timings file.")
        return {"video_id": video_id, "candidates": []}

    print(f"Found {len(candidates)} candidate clips to process.")

    # 2. Load original video metadata
    source_meta = load_source_video_metadata(work_dir)
    original_title = source_meta.get("title", "")
    if original_title:
        print(f"Source video title: {original_title}")

    # 3. Generate metadata for each candidate
    generated_candidates = []
    for cand in candidates:
        cand_id = cand.get("candidate_id", 1)
        duration_s = float(cand.get("total_clip_duration_s", 0.0))
        combined_text = cand.get("combined_text", "")
        print(f"\nProcessing Candidate {cand_id} ({duration_s:.1f}s)...")

        meta = generate_for_candidate(
            cand=cand,
            original_title=original_title,
        )

        title = meta["title"]
        description = meta["description"]
        hashtags = meta["hashtags"]
        tags = meta["tags"]

        print(f"  ✓ Title: {title}")
        print(f"  ✓ Description: {description[:80]}...")
        print(f"  ✓ Hashtags: {' '.join(hashtags)}")

        record = {
            "video_id": video_id,
            "candidate_id": cand_id,
            "title": title,
            "description": description,
            "hashtags": hashtags,
            "tags": tags,
            "duration_s": duration_s,
            "transcript": combined_text,
            "hook_reason": cand.get("reason", ""),
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        generated_candidates.append(record)

        # Write per-candidate JSON
        cand_json_file = work_dir / f"clip_cand{cand_id}_metadata.json"
        with open(cand_json_file, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2)

        # Write per-candidate TXT (ready to copy/paste)
        cand_txt_file = work_dir / f"clip_cand{cand_id}_info.txt"
        with open(cand_txt_file, "w", encoding="utf-8") as f:
            f.write(f"TITLE:\n{title}\n\n")
            f.write(f"DESCRIPTION:\n{description}\n\n")
            f.write(f"HASHTAGS:\n{' '.join(hashtags)}\n\n")
            f.write(f"TAGS:\n{', '.join(tags)}\n\n")
            f.write(f"DURATION: {duration_s:.1f}s\n\n")
            f.write(f"TRANSCRIPT:\n{combined_text}\n")

        print(f"  Saved: {cand_json_file.name} & {cand_txt_file.name}")

    # 4. Write unified manifest
    manifest = {
        "video_id": video_id,
        "source_title": original_title,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "candidate_count": len(generated_candidates),
        "candidates": generated_candidates,
    }
    manifest_path = work_dir / "clip_metadata_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nUnified metadata manifest saved to {manifest_path}")
    return manifest


def main():
    parser = argparse.ArgumentParser(
        description="Generate title, description, and hashtags for candidate video clips using LLM."
    )
    parser.add_argument(
        "target",
        help="Video ID or directory path containing final_clip_timings.json",
    )
    args = parser.parse_args()
    generate_clip_metadata(args.target)


if __name__ == "__main__":
    main()
