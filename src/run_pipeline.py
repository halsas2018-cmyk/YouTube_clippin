#!/usr/bin/env python3
"""
Unified pipeline runner for YouTube clip generation.

Runs all 12 stages in sequence and stages the Remotion render package.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def extract_video_id(url: str) -> str:
    """Extract YouTube video ID from various URL formats."""
    import re
    patterns = [
        r'(?:v=|/)([0-9A-Za-z_-]{11}).*',
        r'youtu\.be/([0-9A-Za-z_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    raise ValueError(f"Could not extract video ID from URL: {url}")


def run_stage(stage_num: int, total_stages: int, cmd: list[str], cwd: Path) -> None:
    """Run a single pipeline stage with subprocess."""
    print(f"\n[{stage_num}/{total_stages}] Running: {' '.join(cmd)}")
    sys.stdout.flush()
    subprocess.run(cmd, check=True, cwd=cwd)
    print(f"[{stage_num}/{total_stages}] ✓ Completed")


def copy_remotion_assets(video_id: str, project_root: Path) -> dict:
    """
    Copy render-time manifests and assets from media/downloads/<VIDEO_ID>/
    to remotion/public/media/downloads/<VIDEO_ID>/.
    Returns summary info.
    """
    src_base = project_root / "media" / "downloads" / video_id
    dst_base = project_root / "remotion" / "public" / "media" / "downloads" / video_id

    # Ensure destination exists
    dst_base.mkdir(parents=True, exist_ok=True)

    # Manifests to copy
    manifests = [
        "final_clip_timings.json",
        "caption_manifest.json",
        "emoji_manifest.json",
        "broll_manifest.json",
    ]

    copied_manifests = []
    for manifest in manifests:
        src = src_base / manifest
        dst = dst_base / manifest
        if src.exists():
            shutil.copy2(src, dst)
            copied_manifests.append(manifest)
            print(f"  Copied manifest: {manifest}")
        else:
            print(f"  Warning: Manifest not found: {manifest}")

    # Discover candidate IDs from final_clip_timings.json
    candidate_ids = []
    timings_path = src_base / "final_clip_timings.json"
    if timings_path.exists():
        with open(timings_path, "r") as f:
            timings = json.load(f)
        for cand in timings.get("candidates", []):
            candidate_ids.append(cand.get("candidate_id"))

    # Copy section MP4s (for all candidates)
    src_sections = src_base / "sections"
    dst_sections = dst_base / "sections"
    if src_sections.exists():
        if dst_sections.exists():
            shutil.rmtree(dst_sections)
        shutil.copytree(src_sections, dst_sections)
        print(f"  Copied sections directory")

    # Copy B-roll assets
    src_broll = src_base / "media" / "broll"
    dst_broll = dst_base / "media" / "broll"
    if src_broll.exists():
        if dst_broll.exists():
            shutil.rmtree(dst_broll)
        shutil.copytree(src_broll, dst_broll)
        print(f"  Copied B-roll assets")

    # Copy audio assets (mixed.wav)
    src_audio = src_base / "media" / "audio"
    dst_audio = dst_base / "media" / "audio"
    if src_audio.exists():
        if dst_audio.exists():
            shutil.rmtree(dst_audio)
        shutil.copytree(src_audio, dst_audio)
        print(f"  Copied audio assets")

    # Copy other media files that might be in the source (like section_001.mp4 at root level)
    for file_name in ["section_001.mp4", "mixed.m4a", "mixed.wav"]:
        src_file = src_base / file_name
        if src_file.exists():
            shutil.copy2(src_file, dst_base / file_name)
            print(f"  Copied {file_name}")

    return {
        "video_id": video_id,
        "candidate_count": len(candidate_ids),
        "candidate_ids": candidate_ids,
        "staging_dir": str(dst_base),
        "copied_manifests": copied_manifests,
    }


def main():
    parser = argparse.ArgumentParser(
        prog="run-pipeline",
        description="Run the full YouTube clip generation pipeline for a single video URL",
    )
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument(
        "--from-stage",
        type=int,
        choices=range(1, 13),
        metavar="N",
        default=1,
        help="Start pipeline at stage N (1-12). Stages 1..N-1 are skipped. Default: 1",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    video_id = extract_video_id(args.url)

    print(f"=" * 60)
    print(f"Pipeline started for video: {video_id}")
    print(f"Starting from stage: {args.from_stage}")
    print(f"Project root: {project_root}")
    print(f"=" * 60)

    # Define all 12 stages
    stages = [
        (1, ["python3", "-m", "src.youtube_ingestion", args.url]),
        (2, ["python3", "-m", "src.transcript_discovery", video_id]),
        (3, ["python3", "-m", "src.section_extraction", video_id, "--overwrite"]),
        (4, ["python3", "-m", "src.whisperx_alignment.align_sections", video_id]),
        (5, ["python3", "-m", "src.clip_timing.clip_timing", f"media/downloads/{video_id}"]),
        (6, ["python3", "-m", "src.clip_timing.caption_planner", f"media/downloads/{video_id}"]),
        (7, ["python3", "-m", "src.emoji_planning.emoji_planner", video_id]),
        (8, ["python3", "-m", "src.broll_planning.broll_planner", f"media/downloads/{video_id}"]),
        (9, ["python3", "-m", "src.broll_planning.broll_acquirer", f"media/downloads/{video_id}"]),
        (10, ["python3", "-m", "src.audio_planning.audio_planning", video_id]),
        (11, ["python3", "-m", "src.audio_planning.audio_acquisition_final", video_id, "--force"]),
        (12, ["python3", "-m", "src.audio_planning.mix_audio", video_id]),
    ]

    total_stages = len(stages)

    # Run all stages
    for stage_num, cmd in stages:
        if stage_num < args.from_stage:
            print(f"\n[{stage_num}/{total_stages}] [SKIP] {' '.join(cmd)}")
            continue
        try:
            run_stage(stage_num, total_stages, cmd, project_root)
        except subprocess.CalledProcessError as e:
            print(f"\n[{stage_num}/{total_stages}] ✗ FAILED with exit code {e.returncode}")
            sys.exit(1)

    # Stage 13: Prepare Remotion render package
    print(f"\n[{total_stages + 1}/{total_stages + 1}] Staging Remotion render package...")
    summary = copy_remotion_assets(video_id, project_root)

    # Final summary
    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)
    print(f"Video ID:        {summary['video_id']}")
    print(f"Candidate count: {summary['candidate_count']}")
    print(f"Candidate IDs:   {summary['candidate_ids']}")
    print(f"Staging dir:     {summary['staging_dir']}")
    print(f"Copied manifests: {', '.join(summary['copied_manifests'])}")
    print("=" * 60)
    print("SUCCESS: Ready for Remotion render")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())