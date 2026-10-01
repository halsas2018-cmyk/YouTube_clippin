#!/usr/bin/env python3
import json
import subprocess
from pathlib import Path
from dataclasses import asdict, dataclass, field
from typing import Any, List, Dict

@dataclass
class SectionMetadata:
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

def probe_media_info(file_path: Path) -> dict[str, Any]:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries",
        "format=duration,size,bit_rate:stream=index,codec_name,codec_type,width,height,duration",
        "-of", "json",
        str(file_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(res.stdout)

def probe_media_duration(file_path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    val = res.stdout.strip()
    return round(float(val), 3) if val else 0.0

def main():
    video_id = "S-7VkwSU0gs"
    base_dir = Path("/root/youtubr_clipper/media/downloads") / video_id
    padded_file = base_dir / "padded_ranges.json"
    sections_dir = base_dir / "sections"

    with open(padded_file, "r", encoding="utf-8") as f:
        padded_data = json.load(f)

    video_url = f"https://www.youtube.com/watch?v={video_id}"
    meta_path = base_dir / "metadata.json"
    if meta_path.exists():
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            if "webpage_url" in meta and meta["webpage_url"]:
                video_url = meta["webpage_url"]
        except Exception as exc:
            print(f"Warning: Could not read webpage_url from {meta_path}: {exc}")

    extracted_sections: List[SectionMetadata] = []
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

            print(f"Probing {target_media_file.name}...")
            probed_duration = probe_media_duration(target_media_file)
            probe_info = probe_media_info(target_media_file)
            format_info = probe_info.get("format", {})
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
                file_name=target_media_file.name,
                file_path=str(target_media_file),
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
            print(f"  Written: {sidecar_path}")

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
    print(f"\nManifest written: {manifest_path}")

if __name__ == "__main__":
    main()