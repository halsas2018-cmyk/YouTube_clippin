#!/usr/bin/env python3
"""
Stage 12 — Audio mixing.

Combines background music + SFX events from the planning manifest into a
single mixed MP3 (or WAV if inputs are WAV placeholders) using ffmpeg.

Output: media/audio/mixed_cand{N}.mp3
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import tempfile
import wave
import struct
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_json(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def save_json(data: dict, path: str) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def get_audio_duration(file_path: str) -> float:
    """Use ffprobe to get audio duration in seconds."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


def is_mp3(path: str) -> bool:
    return path.lower().endswith(".mp3")


# ---------------------------------------------------------------------------
# ffmpeg-based MP3/WAV mixing
# ---------------------------------------------------------------------------

def build_ffmpeg_mix_command(
    bg_path: str,
    sfx_assets: dict[str, str],        # type -> local_path
    sfx_events: list[dict],
    speech_ducking: list[dict],
    bg_volume_base: float,
    total_duration: float,
    output_path: str,
) -> list[str]:
    """
    Build an ffmpeg command that:
    1. Trims/loops background music to total_duration
    2. Applies volume + ducking via amix + volume filters
    3. Mixes in SFX at precise timestamps using adelay
    4. Outputs to output_path (mp3 or wav based on extension)
    """
    inputs: list[str] = []
    filter_parts: list[str] = []

    # --- Input 0: background music (looped/trimmed to total_duration) ---
    inputs += ["-stream_loop", "-1", "-i", bg_path]

    # Trim background to exact duration and apply base volume
    # Build volume filter string with ducking using volume envelope
    # We use the `volume` filter with `enable` expressions for ducking
    duck_filters: list[str] = []
    for region in speech_ducking:
        start = region["start"]
        end = region["end"]
        duck = region.get("duck_amount", 0.7)
        reduced_vol = bg_volume_base * (1.0 - duck)
        # ffmpeg volume filter with enable expression
        duck_filters.append(
            f"volume={reduced_vol:.4f}:enable='between(t,{start:.3f},{end:.3f})'"
        )

    # Chain: trim → base volume → ducking regions
    bg_filter = f"[0:a]atrim=0:{total_duration:.3f},asetpts=PTS-STARTPTS,volume={bg_volume_base:.4f}"

    # Apply each ducking region as a sequential volume override
    # Build a single volume expression covering all duck regions
    if speech_ducking:
        # Compose a volume expression: base outside speech, reduced inside speech
        # We use a piecewise expression
        vol_expr_parts: list[str] = []
        for region in speech_ducking:
            s = region["start"]
            e = region["end"]
            duck = region.get("duck_amount", 0.7)
            reduced = 1.0 - duck  # multiplier relative to base (base already applied)
            vol_expr_parts.append(f"between(t,{s:.3f},{e:.3f})*{reduced:.4f}")
        # If in any speech region, use that reduced factor; else use 1.0
        vol_expr = "if(gt(" + "+".join(vol_expr_parts) + ",0)," + "+".join(vol_expr_parts) + ",1.0)"
        bg_filter += f",volume='{vol_expr}'"

    # Collect SFX stream indices (starting from 1 since 0 is bg)
    sfx_streams: list[str] = []
    sfx_input_idx = 1

    for event in sfx_events:
        event_time = event["time"]
        event_type = event["type"]
        event_vol = event.get("volume", 0.4)

        if event_type in ("whoosh_in", "whoosh_out"):
            asset_key = "whoosh"
        elif event_type == "click":
            asset_key = "click"
        else:
            continue

        sfx_path = sfx_assets.get(asset_key)
        if not sfx_path or not os.path.exists(sfx_path):
            continue

        inputs += ["-i", sfx_path]
        delay_ms = int(event_time * 1000)
        # Apply volume and delay to each SFX input
        sfx_label = f"sfx{sfx_input_idx}"
        filter_parts.append(
            f"[{sfx_input_idx}:a]volume={event_vol:.4f},adelay={delay_ms}|{delay_ms},apad=whole_dur={total_duration:.3f}[{sfx_label}]"
        )
        sfx_streams.append(f"[{sfx_label}]")
        sfx_input_idx += 1

    bg_label = "[bg_processed]"
    filter_parts.insert(0, f"{bg_filter}{bg_label}")

    # Mix all streams
    all_streams = [bg_label] + sfx_streams
    n_streams = len(all_streams)
    mix_inputs = "".join(all_streams)
    filter_parts.append(
        f"{mix_inputs}amix=inputs={n_streams}:duration=shortest:normalize=0[out]"
    )

    filter_complex = ";".join(filter_parts)

    # Output codec based on extension
    out_ext = Path(output_path).suffix.lower()
    if out_ext == ".mp3":
        codec_args = ["-c:a", "libmp3lame", "-q:a", "2"]
    else:
        codec_args = ["-c:a", "pcm_s16le"]

    cmd = (
        ["ffmpeg", "-y"]
        + inputs
        + ["-filter_complex", filter_complex]
        + ["-map", "[out]"]
        + codec_args
        + ["-t", str(total_duration), output_path]
    )
    return cmd


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
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
    audio_dir = os.path.join(base_dir, "media", "audio")

    planning_path = os.path.join(base_dir, f"audio_planning_manifest_cand{candidate_id}.json")
    acquisition_path = os.path.join(audio_dir, "acquisition_manifest.json")

    planning = load_json(planning_path)
    acquisition = load_json(acquisition_path)

    total_duration: float = planning["total_clip_duration_s"]
    speech_ducking: list = planning["speech_ducking"]
    sfx_events: list = planning["sfx"]
    bg_volume_base: float = planning["background_music"][0]["volume"]

    print(f"Mixing audio for {video_id} candidate {candidate_id}")
    print(f"  Duration       : {total_duration:.3f}s")
    print(f"  BG volume      : {bg_volume_base}")
    print(f"  Ducking regions: {len(speech_ducking)}")
    print(f"  SFX events     : {len(sfx_events)}")

    # --- Locate audio assets ---
    asset_map: dict[str, str] = {}
    bg_path: str = ""
    for asset in acquisition["audio_assets"]:
        local_path = asset["local_path"]
        if not os.path.exists(local_path):
            print(f"⚠ Asset not found, skipping: {local_path}")
            continue
        if asset["type"] == "background_music":
            bg_path = local_path
        else:
            asset_map[asset["type"]] = local_path

    if not bg_path:
        print("✗ Background music asset not found — cannot mix.")
        sys.exit(1)

    print(f"\n  BG music: {bg_path}")
    for k, v in asset_map.items():
        print(f"  SFX {k}: {v}")

    # --- Determine output path (always MP3 unless background is WAV placeholder) ---
    if is_mp3(bg_path) or any(is_mp3(p) for p in asset_map.values()):
        output_ext = ".mp3"
    else:
        output_ext = ".wav"

    output_path = os.path.join(audio_dir, f"mixed_cand{candidate_id}{output_ext}")

    # --- Build and run ffmpeg ---
    cmd = build_ffmpeg_mix_command(
        bg_path=bg_path,
        sfx_assets=asset_map,
        sfx_events=sfx_events,
        speech_ducking=speech_ducking,
        bg_volume_base=bg_volume_base,
        total_duration=total_duration,
        output_path=output_path,
    )

    print(f"\nRunning ffmpeg …")
    print("  " + " ".join(cmd[:8]) + " …")  # print a preview of the command

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("✗ ffmpeg failed:")
        print(result.stderr[-2000:])
        sys.exit(1)

    # --- Validate output ---
    print(f"\n✓ Mixed audio saved: {output_path}")
    actual_duration = get_audio_duration(output_path)
    file_size = os.path.getsize(output_path)
    duration_ok = abs(actual_duration - total_duration) < 0.5

    print(f"  File size   : {file_size:,} bytes")
    print(f"  Duration    : {actual_duration:.3f}s (expected {total_duration:.3f}s)")
    print(f"  Duration OK : {'✓' if duration_ok else '✗'}")

    # --- Save mix manifest ---
    mix_manifest = {
        "video_id": video_id,
        "selected_candidate_id": candidate_id,
        "source_manifests": {
            "audio_planning": planning_path,
            "acquisition": acquisition_path,
        },
        "output_path": output_path,
        "output_format": output_ext.lstrip("."),
        "duration_s": actual_duration,
        "background_music_volume_base": bg_volume_base,
        "speech_ducking_applied": len(speech_ducking),
        "sfx_events_count": len(sfx_events),
        "validation": {
            "duration_ok": duration_ok,
            "file_size_bytes": file_size,
        },
    }
    mix_manifest_path = os.path.join(audio_dir, f"mix_manifest_cand{candidate_id}.json")
    save_json(mix_manifest, mix_manifest_path)
    print(f"\n✓ Mix manifest saved: {mix_manifest_path}")
    print("\nMixing completed successfully.")


if __name__ == "__main__":
    main()