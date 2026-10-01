#!/usr/bin/env python3
"""
Stage 10 — Audio asset acquisition.

Downloads real MP3 audio files from Freesound (background music + SFX).
Falls back to generating a placeholder tone WAV if no API key is set or
if the Freesound request fails.

Requires: FREESOUND_API_KEY in .env (get a free key at freesound.org/apiv2/apply)

Output: media/audio/background_music.mp3, whoosh.mp3, click.mp3
        media/audio/acquisition_manifest.json
"""
from __future__ import annotations

import json
import math
import os
import struct
import sys
import wave
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Load .env
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
except ModuleNotFoundError:
    pass


# ---------------------------------------------------------------------------
# Freesound helpers
# ---------------------------------------------------------------------------

FREESOUND_SEARCH_URL = "https://freesound.org/apiv2/search/text/"
FREESOUND_SOUND_URL = "https://freesound.org/apiv2/sounds/{sound_id}/"

# Duration filter tags for Freesound search
# background music: prefer longer tracks (>= 30s), SFX: short (< 3s)
# NOTE: Duration filters on Freesound API are very slow. We filter client-side instead.
DURATION_FILTERS = {
    "background_music": "",
    "whoosh": "",
    "click": "",
}

# Minimum acceptable durations (client-side filter after search)
MIN_DURATIONS = {
    "background_music": 30.0,
    "whoosh": 0.3,
    "click": 0.05,
}

MAX_DURATIONS = {
    "background_music": None,  # no upper bound
    "whoosh": 3.0,
    "click": 1.0,
}


def freesound_search(query: str, asset_type: str, api_key: str, max_results: int = 20) -> list[dict]:
    """Search Freesound and return a list of hit dicts, filtered by duration client-side."""
    duration_filter = DURATION_FILTERS.get(asset_type, "")
    params: dict = {
        "query": query,
        "token": api_key,
        "fields": "id,name,tags,previews,duration",
        "page_size": max_results,
        "sort": "score",
    }
    if duration_filter:
        params["filter"] = duration_filter
    resp = requests.get(FREESOUND_SEARCH_URL, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results", [])

    # Client-side duration filtering
    min_dur = MIN_DURATIONS.get(asset_type, 0)
    max_dur = MAX_DURATIONS.get(asset_type)
    filtered = []
    for hit in results:
        dur = hit.get("duration")
        if dur is None:
            continue
        if dur < min_dur:
            continue
        if max_dur is not None and dur > max_dur:
            continue
        filtered.append(hit)

    print(f"  Freesound: {len(results)} results → {len(filtered)} after duration filter (min={min_dur}s, max={max_dur})")
    return filtered


def download_mp3(preview_url: str, dest_path: str, api_key: str) -> int:
    """Download a Freesound HQ MP3 preview to dest_path. Returns file size."""
    # Freesound preview URLs need the token as a query param
    sep = "&" if "?" in preview_url else "?"
    url = f"{preview_url}{sep}token={api_key}"
    resp = requests.get(url, timeout=30, stream=True)
    resp.raise_for_status()
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    return os.path.getsize(dest_path)


def acquire_from_freesound(
    query: str,
    asset_type: str,
    dest_path: str,
    api_key: str,
) -> dict | None:
    """Try to find + download a matching sound. Returns asset info dict or None."""
    print(f"  Freesound search: '{query}' (type={asset_type})")
    try:
        hits = freesound_search(query, asset_type, api_key, max_results=5)
    except Exception as exc:
        print(f"  ⚠ Freesound search failed: {exc}")
        return None

    if not hits:
        print(f"  ⚠ No Freesound results for query '{query}'")
        return None

    # Pick the first hit that has an hq-mp3 preview
    for hit in hits:
        previews = hit.get("previews", {})
        mp3_url = previews.get("preview-hq-mp3") or previews.get("preview-lq-mp3")
        if not mp3_url:
            continue
        try:
            size = download_mp3(mp3_url, dest_path, api_key)
            print(f"  ✓ Downloaded: {hit['name']} ({size} bytes) → {dest_path}")
            return {
                "freesound_id": hit["id"],
                "freesound_name": hit["name"],
                "preview_url": mp3_url,
                "duration_s": hit.get("duration"),
                "local_path": dest_path,
            }
        except Exception as exc:
            print(f"  ⚠ Download failed for sound {hit['id']}: {exc}")
            continue

    print(f"  ⚠ Could not download any result for '{query}'")
    return None


# ---------------------------------------------------------------------------
# Placeholder fallback (WAV tone)
# ---------------------------------------------------------------------------

def create_placeholder_wav(file_path: str, duration_seconds: float, sample_rate: int = 44100, amplitude: float = 0.1) -> int:
    """Create a 440 Hz sine-wave WAV as a placeholder when Freesound is unavailable."""
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    nframes = int(duration_seconds * sample_rate)
    with wave.open(file_path, "w") as wf:
        wf.setparams((1, 2, sample_rate, nframes, "NONE", "not compressed"))
        for i in range(nframes):
            t = i / sample_rate
            val = int(amplitude * 32767 * math.sin(2 * math.pi * 440 * t))
            wf.writeframes(struct.pack("<h", val))
    return os.path.getsize(file_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 2 or len(sys.argv) > 3:
        print(f"Usage: {sys.argv[0]} VIDEO_ID [--force]")
        sys.exit(1)
    video_id = sys.argv[1]
    force = len(sys.argv) == 3 and sys.argv[2] == "--force"

    base_dir = f"/root/youtubr_clipper/media/downloads/{video_id}"
    audio_dir = os.path.join(base_dir, "media", "audio")
    os.makedirs(audio_dir, exist_ok=True)

    # Read the LLM-generated search queries from the first candidate's manifest
    # (acquisition is shared across candidates — search queries are per-video)
    planning_path = os.path.join(base_dir, "audio_planning_manifest_cand1.json")
    music_query = "upbeat corporate background"
    whoosh_query = "whoosh swoosh transition"
    click_query = "ui click button"
    total_duration = 30.0  # default; overridden below

    if os.path.exists(planning_path):
        with open(planning_path) as f:
            planning = json.load(f)
        total_duration = planning.get("total_clip_duration_s", total_duration)
        music_query = planning.get("music_search_query", music_query)
        sfx_queries = planning.get("sfx_search_queries", {})
        whoosh_query = sfx_queries.get("whoosh", whoosh_query)
        click_query = sfx_queries.get("click", click_query)
        print(f"Loaded search queries from {planning_path}")
        print(f"  Music query  : {music_query}")
        print(f"  Whoosh query : {whoosh_query}")
        print(f"  Click query  : {click_query}")
    else:
        print(f"⚠ {planning_path} not found — using default queries.")

    # Freesound API key
    api_key = os.environ.get("FREESOUND_API_KEY", "").strip()
    use_freesound = bool(api_key)
    if not use_freesound:
        print("\n⚠ FREESOUND_API_KEY not set — will use placeholder WAV files.")
        print("  Get a free key at: https://freesound.org/apiv2/apply")

    # Asset definitions
    assets_config = [
        {
            "type": "background_music",
            "filename": "background_music.mp3" if use_freesound else "background_music.wav",
            "query": music_query,
            "placeholder_duration": total_duration,
        },
        {
            "type": "whoosh",
            "filename": "whoosh.mp3" if use_freesound else "whoosh.wav",
            "query": whoosh_query,
            "placeholder_duration": 0.5,
        },
        {
            "type": "click",
            "filename": "click.mp3" if use_freesound else "click.wav",
            "query": click_query,
            "placeholder_duration": 0.1,
        },
    ]

    acquisition_manifest: dict = {
        "video_id": video_id,
        "total_clip_duration_s": total_duration,
        "audio_assets": [],
        "acquisition_summary": {
            "acquired": 0,
            "failed": 0,
            "skipped": 0,
            "total_attempted": len(assets_config),
        },
    }

    for cfg in assets_config:
        local_path = os.path.join(audio_dir, cfg["filename"])

        # Skip if already exists and not forcing
        if os.path.exists(local_path) and os.path.getsize(local_path) > 0 and not force:
            print(f"\nSkipping {cfg['type']}: {local_path} already exists")
            acquisition_manifest["acquisition_summary"]["skipped"] += 1
            acquisition_manifest["audio_assets"].append({
                "asset_id": f"audio_{cfg['type']}_001",
                "type": cfg["type"],
                "local_path": local_path,
                "source_url": "local_file_previously_acquired",
                "provider": "freesound" if use_freesound else "placeholder",
                "license": "CC — see Freesound for details" if use_freesound else "placeholder",
                "query": cfg["query"],
                "timing": {
                    "start": 0.0 if cfg["type"] == "background_music" else None,
                    "end": total_duration if cfg["type"] == "background_music" else None,
                },
            })
            continue

        print(f"\nAcquiring: {cfg['type']} …")
        asset_info = None

        if use_freesound:
            asset_info = acquire_from_freesound(cfg["query"], cfg["type"], local_path, api_key)

        if asset_info is not None:
            acquisition_manifest["acquisition_summary"]["acquired"] += 1
            acquisition_manifest["audio_assets"].append({
                "asset_id": f"audio_{cfg['type']}_001",
                "type": cfg["type"],
                "local_path": local_path,
                "source_url": asset_info.get("preview_url", ""),
                "provider": "freesound",
                "license": "CC — see Freesound for details",
                "freesound_id": asset_info.get("freesound_id"),
                "freesound_name": asset_info.get("freesound_name"),
                "query": cfg["query"],
                "timing": {
                    "start": 0.0 if cfg["type"] == "background_music" else None,
                    "end": total_duration if cfg["type"] == "background_music" else None,
                },
            })
        else:
            # Fallback: placeholder WAV
            wav_path = local_path.replace(".mp3", ".wav")
            print(f"  Creating placeholder WAV: {wav_path}")
            try:
                create_placeholder_wav(wav_path, cfg["placeholder_duration"])
                acquisition_manifest["acquisition_summary"]["acquired"] += 1
                acquisition_manifest["audio_assets"].append({
                    "asset_id": f"audio_{cfg['type']}_001",
                    "type": cfg["type"],
                    "local_path": wav_path,
                    "source_url": f"placeholder://{cfg['type']}",
                    "provider": "placeholder",
                    "license": "placeholder (sine tone)",
                    "query": cfg["query"],
                    "timing": {
                        "start": 0.0 if cfg["type"] == "background_music" else None,
                        "end": total_duration if cfg["type"] == "background_music" else None,
                    },
                })
            except Exception as exc:
                print(f"  ✗ Failed to create placeholder: {exc}")
                acquisition_manifest["acquisition_summary"]["failed"] += 1

    # Save acquisition manifest
    manifest_path = os.path.join(audio_dir, "acquisition_manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(acquisition_manifest, f, indent=2)
    print(f"\n✓ Acquisition manifest saved: {manifest_path}")

    summary = acquisition_manifest["acquisition_summary"]
    print(f"  Acquired : {summary['acquired']}")
    print(f"  Skipped  : {summary['skipped']}")
    print(f"  Failed   : {summary['failed']}")

    # Validate all assets exist
    print("\n--- Validation ---")
    all_ok = True
    for asset in acquisition_manifest["audio_assets"]:
        exists = os.path.exists(asset["local_path"]) and os.path.getsize(asset["local_path"]) > 0
        status = "✓" if exists else "✗"
        print(f"  {status} {asset['type']}: {asset['local_path']}")
        if not exists:
            all_ok = False

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()