"""CLI entry point for the transcript-discovery / clip-selection stage.

Usage (from project root)::

    python -m src.transcript_discovery <video_id>
    python -m src.transcript_discovery <video_id> --retries 3
    python -m src.transcript_discovery <video_id> --quiet

Environment variables (see llm_client.py for full docs):
    CLIPPER_LLM_PROVIDER   openai | anthropic | google  (default: openai)
    CLIPPER_LLM_MODEL      model name override
    OPENAI_API_KEY         (or ANTHROPIC_API_KEY / GEMINI_API_KEY)
"""
import argparse
import json
import sys

from .clipper import run_clipper


def main() -> int:
    """CLI entry point — returns process exit code."""
    parser = argparse.ArgumentParser(
        prog="transcript-discovery",
        description=(
            "Analyse a saved en.json transcript with an LLM and produce "
            "clip candidates (clip_candidates.json)."
        ),
    )
    parser.add_argument(
        "video_id",
        help="YouTube video ID whose transcript to analyse (e.g. FltNsyPXNdo)",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=2,
        help="Max LLM retries on validation failure (default: 2)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress messages",
    )
    args = parser.parse_args()

    try:
        result = run_clipper(
            args.video_id,
            max_llm_retries=args.retries,
            verbose=not args.quiet,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(json.dumps({
        "video_id": result.video_id,
        "output_path": str(result.output_path),
        "candidate_count": len(result.candidates),
        "warnings": result.warnings,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
