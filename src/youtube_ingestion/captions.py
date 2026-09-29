"""YouTube transcript extraction via youtube-transcript-api.

Uses ``youtube-transcript-api`` (instance API) to list available transcripts
and fetch their content with rough per-segment timestamps.
"""
from youtube_transcript_api import YouTubeTranscriptApi


def fetch_all_transcripts(
    video_id: str,
    languages: list[str] | None = None,
) -> list[dict]:
    """List all available transcripts and fetch their content.

    Args:
        video_id: YouTube video ID (not the full URL).
        languages: Optional list of language codes to fetch.
            If *None*, all available transcripts are retrieved.

    Returns:
        A list of dicts, each containing::

            {
                "video_id": str,
                "language_code": str,
                "language": str,
                "is_generated": bool,
                "is_translatable": bool,
                "translation_languages": list[str],
                "segments": [
                    {"text": str, "start": float, "duration": float},
                    ...
                ],
            }

    Raises:
        youtube_transcript_api.TranscriptsDisabled:
            If transcripts are not available for this video.
    """
    api = YouTubeTranscriptApi()
    transcript_list = api.list(video_id)

    results: list[dict] = []
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
    return results
