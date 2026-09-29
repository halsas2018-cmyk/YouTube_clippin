"""
B-roll acquisition module.
Consumes broll_manifest.json, searches Pexels (with Pixabay fallback), downloads video/image assets for
USE_BROLL and ORIGINAL_WITH_OVERLAY slots under media/broll/, and updates broll_manifest.json with acquisition metadata.

Following the relevant acquisition approach from scary_stories/asset_collector.py:
  - MIN_CLIP_WIDTH filter (480px) to enforce usable resolution
  - Portrait orientation enforcement (h > w) for Shorts
  - Smallest-file selection (by reported byte size) to keep downloads small
  - Exponential backoff retries
  - 10 KB minimum file-size validation on download
  - Idempotency: skip slots whose file already exists with acquisition data
"""

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

PEXELS_VIDEO_API = "https://api.pexels.com/videos/search"
PEXELS_PHOTO_API = "https://api.pexels.com/v1/search"
PIXABAY_VIDEO_API = "https://pixabay.com/api/videos/"
PIXABAY_PHOTO_API = "https://pixabay.com/api/"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# Minimum usable clip width — matches scary_stories MIN_CLIP_WIDTH.
MIN_CLIP_WIDTH = 480

# Minimum downloaded file size to be considered valid (bytes).
MIN_FILE_BYTES = 10 * 1024  # 10 KB, matching scary_stories

# Delay between API calls to respect rate limits.
REQUEST_DELAY = 0.5


def _get_pexels_key() -> str:
    return os.environ.get("PEXELS_API_KEY", "").strip()


def _get_pixabay_key() -> str:
    return os.environ.get("PIXABAY_API_KEY", "").strip()


def _search_pexels_video(query: str, api_key: str) -> Optional[Dict[str, Any]]:
    """Search Pexels for portrait video clips.

    Collects ALL usable video files across all returned videos that are
    portrait (h > w) and >= MIN_CLIP_WIDTH, then picks the SMALLEST by
    reported byte size (scary_stories approach) to keep downloads small.
    """
    if not api_key:
        return None
    url = f"{PEXELS_VIDEO_API}?query={requests.utils.quote(query)}&per_page=5&orientation=portrait&size=small"
    headers = {"Authorization": api_key, "User-Agent": USER_AGENT}
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                videos = data.get("videos", [])
                if not videos:
                    return None
                # Collect every usable portrait file meeting MIN_CLIP_WIDTH.
                usable: List[Dict[str, Any]] = []
                for video in videos:
                    files = video.get("video_files", [])
                    for f in files:
                        w, h = f.get("width", 0), f.get("height", 0)
                        if h > w and w >= MIN_CLIP_WIDTH and f.get("link"):
                            usable.append({
                                "url": f["link"],
                                "video": video,
                                "width": w,
                                "height": h,
                                "size_bytes": f.get("size", 0) or 0,
                                "duration": video.get("duration", 10),
                            })
                if usable:
                    # Sort by size, then duration; pick the smallest.
                    usable.sort(key=lambda c: (c["size_bytes"] or float("inf"), c["duration"]))
                    chosen = usable[0]
                    file_info_url = chosen["url"]
                    video = chosen["video"]
                    user = video.get("user", {})
                    return {
                        "provider": "pexels",
                        "media_type": "video",
                        "download_url": file_info_url,
                        "source_url": video.get("url", file_info_url),
                        "attribution": {
                            "author": user.get("name", "Pexels Creator"),
                            "author_url": user.get("url", "https://www.pexels.com"),
                            "license": "Pexels License (Free to use)",
                        },
                        "ext": ".mp4",
                    }
            # Non-200 or no usable results — fall through to retry
            if resp.status_code != 200:
                print(f"  Pexels video API returned {resp.status_code} for '{query}'")
        except Exception as e:
            if attempt == 2:
                print(f"Pexels video search error for query '{query}': {e}")
            wait = (attempt + 1) * 2
            time.sleep(wait)
            continue
    return None


def _search_pexels_photo(query: str, api_key: str) -> Optional[Dict[str, Any]]:
    """Search Pexels for portrait photos.

    Picks the first portrait photo result (scary_stories uses src.portrait
    which is already pre-cropped to a fixed small portrait resolution).
    """
    if not api_key:
        return None
    url = f"{PEXELS_PHOTO_API}?query={requests.utils.quote(query)}&per_page=5&orientation=portrait"
    headers = {"Authorization": api_key, "User-Agent": USER_AGENT}
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                photos = data.get("photos", [])
                if not photos:
                    return None
                photo = photos[0]
                src = photo.get("src", {})
                photo_url = src.get("portrait") or src.get("large") or src.get("original")
                return {
                    "provider": "pexels",
                    "media_type": "image",
                    "download_url": photo_url,
                    "source_url": photo.get("url", photo_url),
                    "attribution": {
                        "author": photo.get("photographer", "Pexels Creator"),
                        "author_url": photo.get("photographer_url", "https://www.pexels.com"),
                        "license": "Pexels License (Free to use)",
                    },
                    "ext": ".jpg",
                }
            if resp.status_code != 200:
                print(f"  Pexels photo API returned {resp.status_code} for '{query}'")
        except Exception as e:
            if attempt == 2:
                print(f"Pexels photo search error for query '{query}': {e}")
            wait = (attempt + 1) * 2
            time.sleep(wait)
            continue
    return None


def _search_pixabay_video(query: str, api_key: str) -> Optional[Dict[str, Any]]:
    """Search Pixabay for portrait video clips.

    Iterates all quality tiers (toy, small, medium, large) for each hit,
    collects all portrait files (h > w) with width >= MIN_CLIP_WIDTH,
    and picks the SMALLEST — matching the scary_stories Pixabay approach.
    """
    if not api_key:
        return None
    url = f"{PIXABAY_VIDEO_API}?key={api_key}&q={requests.utils.quote(query)}&per_page=5&video_type=all"
    headers = {"User-Agent": USER_AGENT}
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                hits = data.get("hits", [])
                if not hits:
                    return None
                # Collect all usable portrait video files across all hits.
                usable: List[Dict[str, Any]] = []
                for hit in hits:
                    videos = hit.get("videos", {})
                    for quality in ["tiny", "small", "medium", "large"]:
                        if quality not in videos:
                            continue
                        v = videos[quality]
                        w, h = v.get("width", 0), v.get("height", 0)
                        if h > w and w >= MIN_CLIP_WIDTH and v.get("url"):
                            usable.append({
                                "url": v["url"],
                                "hit": hit,
                                "width": w,
                                "height": h,
                                "size_bytes": v.get("size", 0) or 0,
                                "duration": hit.get("duration", 10),
                            })
                if usable:
                    # Pick smallest by size, then shortest duration.
                    usable.sort(key=lambda c: (c["size_bytes"] or float("inf"), c["duration"]))
                    chosen = usable[0]
                    v_info_url = chosen["url"]
                    hit = chosen["hit"]
                    return {
                        "provider": "pixabay",
                        "media_type": "video",
                        "download_url": v_info_url,
                        "source_url": hit.get("pageURL", v_info_url),
                        "attribution": {
                            "author": hit.get("user", "Pixabay Creator"),
                            "author_url": f"https://pixabay.com/users/{hit.get('user')}-{hit.get('user_id')}/",
                            "license": "Pixabay Content License (Free to use)",
                        },
                        "ext": ".mp4",
                    }
            if resp.status_code != 200:
                print(f"  Pixabay video API returned {resp.status_code} for '{query}'")
        except Exception as e:
            if attempt == 2:
                print(f"Pixabay video search error for query '{query}': {e}")
            wait = (attempt + 1) * 2
            time.sleep(wait)
            continue
    return None


def _search_pixabay_photo(query: str, api_key: str) -> Optional[Dict[str, Any]]:
    """Search Pixabay for portrait photos."""
    if not api_key:
        return None
    url = f"{PIXABAY_PHOTO_API}?key={api_key}&q={requests.utils.quote(query)}&per_page=5&image_type=photo"
    headers = {"User-Agent": USER_AGENT}
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                hits = data.get("hits", [])
                if not hits:
                    return None
                hit = hits[0]
                photo_url = hit.get("webformatURL") or hit.get("largeImageURL")
                return {
                    "provider": "pixabay",
                    "media_type": "image",
                    "download_url": photo_url,
                    "source_url": hit.get("pageURL", photo_url),
                    "attribution": {
                        "author": hit.get("user", "Pixabay Creator"),
                        "author_url": f"https://pixabay.com/users/{hit.get('user')}-{hit.get('user_id')}/",
                        "license": "Pixabay Content License (Free to use)",
                    },
                    "ext": ".jpg",
                }
            if resp.status_code != 200:
                print(f"  Pixabay photo API returned {resp.status_code} for '{query}'")
        except Exception as e:
            if attempt == 2:
                print(f"Pixabay photo search error for query '{query}': {e}")
            wait = (attempt + 1) * 2
            time.sleep(wait)
            continue
    return None


def _download_file(download_url: str, target_path: Path) -> bool:
    """Download a file with retries and exponential backoff.

    Enforces MIN_FILE_BYTES (10 KB) — matches scary_stories' size_kb < 10 check.
    """
    target_path.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": USER_AGENT}
    for attempt in range(3):
        try:
            with requests.get(download_url, headers=headers, stream=True, timeout=30) as r:
                r.raise_for_status()
                with open(target_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=64 * 1024):
                        if chunk:
                            f.write(chunk)
            if target_path.exists() and target_path.stat().st_size >= MIN_FILE_BYTES:
                return True
        except Exception as e:
            if attempt == 2:
                print(f"Download failed for {download_url}: {e}")
            target_path.unlink(missing_ok=True)
            wait = (attempt + 1) * 2
            time.sleep(wait)
            continue
    # Final check — if file exists but is too small, remove it.
    if target_path.exists() and target_path.stat().st_size < MIN_FILE_BYTES:
        target_path.unlink(missing_ok=True)
    return False


def acquire_broll_assets(media_dir: str) -> str:
    """Consume broll_manifest.json, acquire assets for USE_BROLL and ORIGINAL_WITH_OVERLAY
    slots under media/broll/, and update broll_manifest.json with acquisition metadata.

    - Acquires assets ONLY for USE_BROLL and ORIGINAL_WITH_OVERLAY decisions.
    - Creates nothing for KEEP_ORIGINAL.
    - Preserves slot IDs, WhisperX timing/provenance, search query, and all
      existing metadata; only adds/refreshes the 'acquisition' sub-block.
    - Idempotent: skips slots whose acquired file already exists on disk.
    """
    media_path = Path(media_dir)
    manifest_file = media_path / "broll_manifest.json"

    if not manifest_file.exists():
        raise FileNotFoundError(f"broll_manifest.json not found in {media_dir}")

    with open(manifest_file, "r") as f:
        manifest_data = json.load(f)

    broll_dir = media_path / "media" / "broll"
    broll_dir.mkdir(parents=True, exist_ok=True)

    pexels_key = _get_pexels_key()
    pixabay_key = _get_pixabay_key()

    provider_counts: Dict[str, int] = {"pexels": 0, "pixabay": 0, "failed": 0}
    acquired_files: List[str] = []

    for cand in manifest_data.get("candidates", []):
        asset_slots = cand.get("asset_slots", [])

        for slot in asset_slots:
            slot_id = slot.get("slot_id")
            search_query = slot.get("search_query", "")

            # --- Idempotency: skip if already acquired and file exists on disk ---
            existing_acq = slot.get("acquisition")
            if existing_acq:
                existing_path_str = existing_acq.get("local_path")
                if existing_path_str and Path(existing_path_str).exists():
                    provider = existing_acq.get("provider", "unknown")
                    if provider in provider_counts:
                        provider_counts[provider] += 1
                    else:
                        provider_counts[provider] = 1
                    acquired_files.append(existing_path_str)
                    time.sleep(REQUEST_DELAY)
                    continue

            # --- Build search-term fallback chain ---
            search_terms = [
                search_query,
                search_query.split()[0] if search_query else "technology",
                "business",
                "abstract",
            ]

            asset_info: Optional[Dict[str, Any]] = None
            for term in search_terms:
                if not term:
                    continue
                # Try Pexels video first, then photo, then Pixabay video, then photo.
                asset_info = _search_pexels_video(term, pexels_key)
                if not asset_info:
                    asset_info = _search_pexels_photo(term, pexels_key)
                if not asset_info:
                    asset_info = _search_pixabay_video(term, pixabay_key)
                if not asset_info:
                    asset_info = _search_pixabay_photo(term, pixabay_key)
                if asset_info:
                    break

            if asset_info:
                ext = asset_info["ext"]
                local_file = broll_dir / f"{slot_id}{ext}"

                # Skip download if file already exists (e.g. from a prior run
                # that didn't update the manifest).
                if local_file.exists() and local_file.stat().st_size >= MIN_FILE_BYTES:
                    success = True
                else:
                    success = _download_file(asset_info["download_url"], local_file)

                if success:
                    provider = asset_info["provider"]
                    provider_counts[provider] += 1

                    slot["acquisition"] = {
                        "provider": provider,
                        "media_type": asset_info["media_type"],
                        "source_url": asset_info["source_url"],
                        "local_path": str(local_file),
                        "file_size_bytes": local_file.stat().st_size,
                        "attribution": asset_info["attribution"],
                    }
                    acquired_files.append(str(local_file))
                else:
                    provider_counts["failed"] += 1
            else:
                provider_counts["failed"] += 1

            time.sleep(REQUEST_DELAY)

    manifest_data["acquisition_summary"] = {
        "acquired_asset_count": len(acquired_files),
        "provider_counts": provider_counts,
    }

    with open(manifest_file, "w") as f:
        json.dump(manifest_data, f, indent=2)

    return str(manifest_file)


if __name__ == "__main__":
    import sys

    dir_arg = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "/root/youtubr_clipper/media/downloads/FltNsyPXNdo"
    )
    out_manifest = acquire_broll_assets(dir_arg)
    print(
        f"Successfully acquired B-roll assets and updated manifest at: {out_manifest}"
    )
