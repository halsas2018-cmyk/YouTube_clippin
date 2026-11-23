"""YouTube transcript extraction via youtube-transcript-api with yt-dlp fallback.

Uses ``youtube-transcript-api`` (instance API) to list and fetch transcripts.
When ``youtube-transcript-api`` is blocked (e.g. anti-bot checks, IP rate limits,
or cloud runner restrictions), falls back to downloading subtitles and
automatic captions via ``yt-dlp``, parsing them into the standard transcript schema.
"""
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from youtube_transcript_api import YouTubeTranscriptApi

from .metadata import YTDLP_PATH, _COOKIES_FILE

_TIME_REGEX = re.compile(
    r"(\d+:\d+(?::\d+)?(?:[.,]\d+)?)\s*-->\s*(\d+:\d+(?::\d+)?(?:[.,]\d+)?)"
)
_TAG_REGEX = re.compile(r"<[^>]+>")


def _parse_timestamp(ts: str) -> float:
    """Parse WebVTT/SRT timestamp string into total seconds."""
    parts = ts.strip().replace(",", ".").split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def parse_json3_subtitles(content: str) -> list[dict]:
    """Parse YouTube JSON3 subtitle format into segments list.

    Returns:
        List of dicts: ``{"text": str, "start": float, "duration": float}``.
    """
    try:
        data = json.loads(content)
    except Exception:
        return []

    segments: list[dict] = []
    for event in data.get("events", []):
        if "tStartMs" not in event:
            continue
        segs = event.get("segs", [])
        text = "".join(seg.get("utf8", "") for seg in segs)
        clean_text = html.unescape(text)
        clean_text = " ".join(clean_text.split()).strip()
        if not clean_text:
            continue
        start = round(event["tStartMs"] / 1000.0, 3)
        duration = round(event.get("dDurationMs", 0) / 1000.0, 3)

        # Skip consecutive duplicate cues with identical text and overlapping start
        if segments and segments[-1]["text"] == clean_text and abs(segments[-1]["start"] - start) < 0.5:
            continue

        segments.append({
            "text": clean_text,
            "start": start,
            "duration": duration,
        })
    return segments


def parse_vtt_subtitles(content: str) -> list[dict]:
    """Parse WebVTT or SRT subtitle content into segments list.

    Normalizes whitespace using " ".join(clean_text.split()).strip() instead
    of joining words with newlines, removes styling tags, unescapes HTML,
    and deduplicates consecutive identical cue segments.

    Returns:
        List of dicts: ``{"text": str, "start": float, "duration": float}``.
    """
    segments: list[dict] = []
    blocks = re.split(r"\r?\n\s*\r?\n", content.strip())
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        time_idx = -1
        for idx, line in enumerate(lines):
            if "-->" in line:
                time_idx = idx
                break
        if time_idx == -1:
            continue
        time_line = lines[time_idx]
        match = _TIME_REGEX.search(time_line)
        if not match:
            continue
        start = _parse_timestamp(match.group(1))
        end = _parse_timestamp(match.group(2))
        duration = max(0.0, round(end - start, 3))

        text_lines = lines[time_idx + 1:]
        raw_text = " ".join(text_lines)
        clean_text = _TAG_REGEX.sub("", raw_text)
        clean_text = html.unescape(clean_text)
        clean_text = " ".join(clean_text.split()).strip()
        if not clean_text:
            continue

        # Avoid consecutive duplicate segments with same/overlapping timing
        if segments and segments[-1]["text"] == clean_text and abs(segments[-1]["start"] - start) < 0.5:
            continue

        segments.append({
            "text": clean_text,
            "start": round(start, 3),
            "duration": duration,
        })
    return segments


def _extract_lang_from_filename(filename: str, video_id: str) -> tuple[str, str]:
    """Extract (language_code, extension) from a subtitle filename.

    Handles formats like:
        '<video_id>.<lang>.<ext>'
        '<video_id>.<lang>-orig.<ext>'
        '<video_id>.<lang>_<region>.<ext>'
        '<video_id>.<ext>'
    """
    path = Path(filename)
    ext = path.suffix.lower().lstrip(".")
    stem = path.stem
    if stem.startswith(video_id + "."):
        lang = stem[len(video_id) + 1:]
    elif "." in stem:
        lang = stem.rsplit(".", 1)[-1]
    else:
        lang = "en"
    lang = lang.replace("_", "-").strip()
    return lang, ext


def fetch_transcripts_via_ytdlp(
    video_id: str,
    languages: list[str] | None = None,
    cookies_file: str | Path | None = None,
    ytdlp_bin: str | None = None,
) -> list[dict]:
    """Download subtitles or auto-captions via yt-dlp and parse into transcript dicts.

    Reuses the existing cookies configuration, normalizes language codes, prevents
    duplicate captions, and ensures English captions produce an 'en' transcript.

    Args:
        video_id: YouTube video ID.
        languages: Optional list of language codes to fetch.
        cookies_file: Optional path to cookies file (defaults to _COOKIES_FILE).
        ytdlp_bin: Optional path to yt-dlp binary (defaults to YTDLP_PATH).

    Returns:
        List of transcript dicts matching the youtube-transcript-api format.
    """
    binary = ytdlp_bin or YTDLP_PATH
    if not shutil.which(binary):
        sys.stderr.write(f"[yt-dlp-subs] yt-dlp binary not found at {binary}\n")
        return []

    cookies_path = cookies_file if cookies_file is not None else _COOKIES_FILE

    # Construct sub-langs argument
    if languages:
        langs_set = set()
        for lang in languages:
            norm = lang.lower().replace("_", "-")
            if norm == "en" or norm.startswith("en-"):
                langs_set.update(["en.*", "en", "en-orig"])
            else:
                langs_set.update([f"{norm}.*", norm])
        sub_langs_arg = ",".join(sorted(langs_set))
    else:
        sub_langs_arg = "en.*,en,en-orig"

    results: list[dict] = []
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_template = os.path.join(tmpdir, "%(id)s.%(ext)s")
            video_url = f"https://www.youtube.com/watch?v={video_id}"

            base_cmd = [
                binary,
                "--skip-download",
                "--write-subs",
                "--write-auto-subs",
                "--sub-langs", sub_langs_arg,
                "--sub-format", "json3/vtt/srt/best",
                "--no-playlist",
                "--no-warnings",
                "-o", out_template,
            ]
            if cookies_path and os.path.exists(str(cookies_path)):
                base_cmd.extend(["--cookies", str(cookies_path)])

            clients_to_try: list[str | None] = [
                None,
                "tv_embedded,mweb",
                "android,ios",
                "web",
            ]

            sub_files: list[Path] = []
            for client in clients_to_try:
                cmd = list(base_cmd)
                if client:
                    cmd.extend(["--extractor-args", f"youtube:player_client={client}"])
                cmd.append(video_url)

                client_label = client if client else "default"
                sys.stderr.write(f"[yt-dlp-subs] Trying subtitles with client={client_label} ...\n")
                subprocess.run(cmd, capture_output=True, text=True)

                sub_files = [
                    p for p in Path(tmpdir).iterdir()
                    if p.is_file()
                    and not p.name.endswith(".part")
                    and p.suffix.lower() in (".json3", ".vtt", ".srt", ".json")
                ]
                if sub_files:
                    sys.stderr.write(
                        f"[yt-dlp-subs] Downloaded {len(sub_files)} subtitle file(s) with client={client_label}\n"
                    )
                    break

            if not sub_files:
                sys.stderr.write(f"[yt-dlp-subs] No subtitles found for video {video_id}\n")
                return []

            # Group downloaded files by language tag
            files_by_lang: dict[str, dict[str, Path]] = {}
            for p in sub_files:
                lang, ext = _extract_lang_from_filename(p.name, video_id)
                if lang not in files_by_lang:
                    files_by_lang[lang] = {}
                files_by_lang[lang][ext] = p

            format_preference = ["json3", "vtt", "srt", "json"]

            # Sort languages: prefer exact manual 'en' first, then other English tracks, then others
            def _lang_sort_key(lang_key: str) -> tuple[int, str]:
                lk = lang_key.lower()
                if lk == "en":
                    return (0, lk)
                if lk.startswith("en"):
                    return (1, lk)
                return (2, lk)

            sorted_langs = sorted(files_by_lang.keys(), key=_lang_sort_key)
            has_english_primary = False

            for lang in sorted_langs:
                formats = files_by_lang[lang]
                target_ext = next((fmt for fmt in format_preference if fmt in formats), None)
                if not target_ext:
                    continue
                target_file = formats[target_ext]
                try:
                    content = target_file.read_text(encoding="utf-8")
                    if target_ext == "json3":
                        segments = parse_json3_subtitles(content)
                    elif target_ext in ("vtt", "srt"):
                        segments = parse_vtt_subtitles(content)
                    else:
                        segments = parse_json3_subtitles(content) or parse_vtt_subtitles(content)
                except Exception as read_exc:
                    sys.stderr.write(f"[yt-dlp-subs] Failed to parse {target_file}: {read_exc}\n")
                    continue

                if not segments:
                    continue

                is_generated = "orig" in lang.lower() or "auto" in lang.lower()
                lang_lower = lang.lower()

                if lang_lower.startswith("en"):
                    # Normalize first encountered English track to canonical 'en'
                    if not has_english_primary:
                        lang_code = "en"
                        lang_name = "English (auto-generated)" if is_generated else "English"
                        has_english_primary = True
                        results.append({
                            "video_id": video_id,
                            "language_code": lang_code,
                            "language": lang_name,
                            "is_generated": is_generated,
                            "is_translatable": True,
                            "translation_languages": [],
                            "segments": segments,
                        })
                    # Avoid duplicate caption tracks for identical English content
                    elif lang_lower not in ("en", "en-orig"):
                        if not any(r["language_code"] == lang for r in results):
                            results.append({
                                "video_id": video_id,
                                "language_code": lang,
                                "language": f"English ({lang})",
                                "is_generated": is_generated,
                                "is_translatable": True,
                                "translation_languages": [],
                                "segments": segments,
                            })
                else:
                    if not any(r["language_code"] == lang for r in results):
                        results.append({
                            "video_id": video_id,
                            "language_code": lang,
                            "language": lang,
                            "is_generated": is_generated,
                            "is_translatable": True,
                            "translation_languages": [],
                            "segments": segments,
                        })

    except Exception as exc:
        sys.stderr.write(f"[yt-dlp-subs] Subtitle extraction failed for {video_id}: {exc}\n")
        return []

    return results


def fetch_all_transcripts(
    video_id: str,
    languages: list[str] | None = None,
) -> list[dict]:
    """List all available transcripts and fetch their content.

    Tries ``youtube-transcript-api`` first. If blocked or if transcripts cannot
    be retrieved, seamlessly falls back to downloading subtitles and automatic
    captions via ``yt-dlp``.

    Args:
        video_id: YouTube video ID (not the full URL).
        languages: Optional list of language codes to fetch.
            If *None*, all available transcripts are retrieved.

    Returns:
        A list of dicts, each containing:
            video_id, language_code, language, is_generated,
            is_translatable, translation_languages, segments.
    """
    results: list[dict] = []
    ytdlp_fallback_needed = False

    try:
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)

        for transcript in transcript_list:
            if languages and transcript.language_code not in languages:
                continue
            fetched = transcript.fetch()
            results.append({
                "video_id": fetched.video_id,
                "language_code": fetched.language_code,
                "language": fetched.language,
                "is_generated": fetched.is_generated,
                "is_translatable": transcript.is_translatable,
                "translation_languages": [
                    lang.language_code for lang in transcript.translation_languages
                ],
                "segments": fetched.to_raw_data(),
            })
        if not results:
            ytdlp_fallback_needed = True
    except Exception as exc:
        sys.stderr.write(
            f"[captions] youtube-transcript-api failed for {video_id} "
            f"({type(exc).__name__}: {exc}). Falling back to yt-dlp.\n"
        )
        ytdlp_fallback_needed = True

    if ytdlp_fallback_needed or not results:
        sys.stderr.write(
            f"[captions] Attempting yt-dlp subtitle/caption download for video: {video_id}\n"
        )
        ytdlp_results = fetch_transcripts_via_ytdlp(video_id, languages=languages)
        if ytdlp_results:
            existing_codes = {r["language_code"] for r in results}
            for y_res in ytdlp_results:
                if y_res["language_code"] not in existing_codes:
                    results.append(y_res)
                    existing_codes.add(y_res["language_code"])

    return results
