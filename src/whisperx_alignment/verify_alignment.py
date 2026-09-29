"""
Verification script for WhisperX alignment outputs.

Checks for FltNsyPXNdo:
  1. Every section has a whisperx_alignment_*.json output file
  2. Every section produces >= 1 word with timestamps
  3. For at least one word per section, verifies mathematically:
       global_start == round(local_start + start_offset, 4)
       global_end   == round(local_end   + start_offset, 4)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def verify_video(video_id: str, sections_dir: Path) -> bool:
    print(f"\n{'='*65}")
    print(f"VERIFICATION REPORT: {video_id}")
    print(f"{'='*65}")

    metadata_path = sections_dir / "sections_metadata.json"
    with open(metadata_path) as f:
        metadata = json.load(f)

    all_pass = True
    for section in metadata["sections"]:
        section_id = section["section_id"]
        start_offset = float(section["start_offset"])

        print(f"\n  [{section_id}]  start_offset={start_offset}s")

        # Check 1: output file exists
        out_path = sections_dir / f"whisperx_alignment_{section_id}.json"
        if not out_path.exists():
            print(f"    FAIL: alignment file not found: {out_path}")
            all_pass = False
            continue
        print(f"    ✓ Output file exists: {out_path.name}")

        with open(out_path) as f:
            data = json.load(f)

        words = data.get("words", [])

        # Check 2: has word-level timestamps
        if not words:
            print(f"    FAIL: no words found in alignment output")
            all_pass = False
            continue
        print(f"    ✓ Word count: {len(words)}")

        # Check 3: mathematical verification on first word
        w = words[0]
        expected_global_start = round(w["local_start"] + start_offset, 4)
        expected_global_end   = round(w["local_end"]   + start_offset, 4)
        actual_global_start   = round(w["global_start"], 4)
        actual_global_end     = round(w["global_end"],   4)

        gs_ok = abs(actual_global_start - expected_global_start) < 1e-9
        ge_ok = abs(actual_global_end   - expected_global_end)   < 1e-9

        print(f"    Math check on word[0]: '{w['word']}'")
        print(f"      local_start={w['local_start']}  +  start_offset={start_offset}")
        print(f"      → expected global_start = {expected_global_start}")
        print(f"      → actual   global_start = {actual_global_start}  {'✓ PASS' if gs_ok else 'FAIL'}")
        print(f"      local_end  ={w['local_end']}  +  start_offset={start_offset}")
        print(f"      → expected global_end   = {expected_global_end}")
        print(f"      → actual   global_end   = {actual_global_end}  {'✓ PASS' if ge_ok else 'FAIL'}")

        if not (gs_ok and ge_ok):
            all_pass = False

    print(f"\n{'='*65}")
    print(f"OVERALL: {'PASS ✓' if all_pass else 'FAIL ✗'}")
    print(f"{'='*65}\n")
    return all_pass


if __name__ == "__main__":
    video_id = sys.argv[1] if len(sys.argv) > 1 else "FltNsyPXNdo"

    this_file = Path(__file__).resolve()
    project_root = this_file.parent.parent.parent
    sections_dir = project_root / "media" / "downloads" / video_id / "sections"

    ok = verify_video(video_id, sections_dir)
    sys.exit(0 if ok else 1)
