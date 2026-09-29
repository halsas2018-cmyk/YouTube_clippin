"""Module entry point — allows ``python -m src.youtube_ingestion <url>``."""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
