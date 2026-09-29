"""YouTube ingestion stage: metadata and transcript extraction via yt-dlp + youtube-transcript-api."""
from .ingester import Ingester, IngestionResult

__all__ = ["Ingester", "IngestionResult"]
