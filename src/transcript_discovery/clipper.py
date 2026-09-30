"""LLM-based clip candidate discovery from a saved transcript.

Workflow
--------
1. Load  ``media/downloads/{video_id}/transcripts/en.json``
2. Flatten segments into a numbered, timestamped plain-text block
3. Send that block + editorial instructions to the LLM via :mod:`llm_client`
4. Validate the returned JSON strictly (schema + range sanity checks)
5. Save   ``media/downloads/{video_id}/clip_candidates.json``

Each clip candidate the LLM returns may contain **multiple usable ranges**
within the candidate section — e.g. skip a weak opening, keep the hook,
skip a tangent, keep the payoff.  The schema enforces that every range is
valid, ordered, non-overlapping, and within the transcript duration.

Public API::

    from src.transcript_discovery.clipper import run_clipper, ClipperResult

    result = run_clipper("FltNsyPXNdo")
    print(result.output_path)
    print(result.candidates)      # list[dict]
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .llm_client import active_config, chat_json

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DOWNLOADS_ROOT = _PROJECT_ROOT / "media" / "downloads"
_OUTPUT_FILENAME = "clip_candidates.json"

# ---------------------------------------------------------------------------
# Clip candidate schema + validation
# ---------------------------------------------------------------------------

_REQUIRED_CANDIDATE_KEYS: set[str] = {"ranges", "combined_text", "reason"}
_REQUIRED_RANGE_KEYS: set[str] = {"start", "end"}


def _validate_candidates(
    candidates: list[Any],
    transcript_duration: float,
) -> list[str]:
    """Return a list of human-readable validation error strings.

    An empty list means all candidates are valid.
    """
    errors: list[str] = []

    if not isinstance(candidates, list):
        return ["Top-level LLM output must be a JSON array of candidates."]

    for i, cand in enumerate(candidates):
        prefix = f"Candidate[{i}]"

        if not isinstance(cand, dict):
            errors.append(f"{prefix}: must be a JSON object, got {type(cand).__name__}")
            continue

        missing = _REQUIRED_CANDIDATE_KEYS - cand.keys()
        if missing:
            errors.append(f"{prefix}: missing required keys {sorted(missing)}")
            continue

        ranges = cand["ranges"]
        if not isinstance(ranges, list) or len(ranges) == 0:
            errors.append(f"{prefix}: 'ranges' must be a non-empty array")
            continue

        prev_end: float = -1.0
        for j, rng in enumerate(ranges):
            rprefix = f"{prefix}.ranges[{j}]"

            if not isinstance(rng, dict):
                errors.append(f"{rprefix}: must be a JSON object")
                continue

            missing_r = _REQUIRED_RANGE_KEYS - rng.keys()
            if missing_r:
                errors.append(f"{rprefix}: missing keys {sorted(missing_r)}")
                continue

            start = rng["start"]
            end = rng["end"]

            if not isinstance(start, (int, float)):
                errors.append(f"{rprefix}: 'start' must be a number")
                continue
            if not isinstance(end, (int, float)):
                errors.append(f"{rprefix}: 'end' must be a number")
                continue

            start = float(start)
            end = float(end)

            if start < 0:
                errors.append(f"{rprefix}: 'start' ({start}) is negative")
            if end <= start:
                errors.append(
                    f"{rprefix}: 'end' ({end}) must be greater than 'start' ({start})"
                )
            if end > transcript_duration + 1.0:  # 1-second tolerance
                errors.append(
                    f"{rprefix}: 'end' ({end}) exceeds transcript duration "
                    f"({transcript_duration:.2f}s)"
                )
            if start < prev_end:
                errors.append(
                    f"{rprefix}: ranges overlap or are out of order "
                    f"(start={start} < previous end={prev_end})"
                )
            prev_end = end

        if not isinstance(cand["combined_text"], str):
            errors.append(f"{prefix}: 'combined_text' must be a string")
        if not isinstance(cand["reason"], str):
            errors.append(f"{prefix}: 'reason' must be a string")

    return errors


# ---------------------------------------------------------------------------
# Transcript helpers
# ---------------------------------------------------------------------------


def _load_transcript(video_id: str) -> dict:
    """Load and return the saved en.json transcript for *video_id*."""
    path = _DOWNLOADS_ROOT / video_id / "transcripts" / "en.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Transcript not found: {path}\n"
            "Run the YouTube ingestion stage first:\n"
            "  python -m src.youtube_ingestion <url>"
        )
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _transcript_duration(segments: list[dict]) -> float:
    """Return the end time of the last segment."""
    if not segments:
        return 0.0
    last = segments[-1]
    return float(last["start"]) + float(last.get("duration", 0.0))


def _format_transcript_for_llm(segments: list[dict]) -> str:
    """Produce a numbered, timestamped plain-text block for the LLM prompt.

    Each line is::

        [  0] 00:00:00.0 – 00:00:05.1 : YouTubers, I have great news.

    The segment index lets the LLM reference a specific segment without
    repeating full text; timestamps give it precise range information.
    """
    lines: list[str] = []
    for idx, seg in enumerate(segments):
        start = float(seg["start"])
        duration = float(seg.get("duration", 0.0))
        end = start + duration
        text = seg["text"].strip()

        def _fmt(s: float) -> str:
            h = int(s // 3600)
            m = int((s % 3600) // 60)
            sec = s % 60
            return f"{h:02d}:{m:02d}:{sec:05.2f}"

        lines.append(f"[{idx:4d}] {_fmt(start)} – {_fmt(end)} : {text}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert short-form video editor reviewing a YouTube transcript.
Your job is to identify the most valuable 30-90 second clip candidates
that would perform well as standalone short-form videos (Reels, Shorts, TikTok).

RANGE SELECTION — SINGLE CONTIGUOUS RANGE IS STRONGLY PREFERRED:
- Default to ONE contiguous time range per candidate.  A single unbroken range
  almost always produces a more watchable, coherent clip than one with jump cuts.
- Use multiple ranges ONLY when ALL of the following are true:
    1. The ranges are very close together in the transcript (the omitted gap is
       short — typically a few sentences at most).
    2. The omitted material is genuinely redundant filler, a mere aside, or an
       obvious repeated phrase — not a meaningful idea or transition.
    3. The resulting combination is completely coherent without the omitted text.
  If you are uncertain whether the omission is truly necessary, keep the gap and
  use a single range instead.
- NEVER stitch together distant sections of the transcript to manufacture a clip.
  Do not jump across topic shifts, segment breaks, or more than a few lines of
  substantive content just to assemble a desirable-sounding clip.
- Never overlap ranges within the same candidate.
- Ranges must be in chronological order.

STANDALONE COHERENCE REQUIREMENTS:
- Every candidate must work as a standalone short-form video without requiring
  any context from outside the selected ranges.
- Each candidate must open at a natural, self-contained sentence boundary.
  Reject any opening that begins mid-thought or with a dangling reference whose
  antecedent lies outside the selected ranges.  Banned openers include (but are
  not limited to) phrases such as:
    "And that…", "And this…", "And they…", "And it…",
    "Here, what you're about to see…", "As I mentioned…", "As I said…",
    "So as we saw…", "Which means…", "That's why…" (when "that" refers to
    something outside the clip), "This is why…" (same condition),
    "They said…", "It turns out…" (when "it" has no antecedent in the clip),
    or any opener whose subject or antecedent is only clear from omitted context.
- Each candidate must end at a natural semantic boundary — a completed thought,
  a punchline, a clear conclusion, or a satisfying resolution.  Do not cut
  mid-sentence or leave an unresolved reference dangling at the end.
- Preserve complete thoughts rather than cutting sentences arbitrarily.
- Every included range must end on a complete thought or natural pause.

SPONSOR / AD-READ AVOIDANCE:
- Avoid selecting ranges that consist primarily of sponsor reads, ad integrations,
  or promotional segments (e.g. "This video is brought to you by…", discount-code
  pitches, product-affiliate plugs unrelated to the video's core subject).
- Exception: if the video's subject is itself a tool, product, or service, and the
  discussion of that product is substantive and educational rather than a paid
  promotional script, it may be selected.
- When stronger, non-sponsor content exists elsewhere in the transcript, always
  prefer it over a sponsor segment.

DIVERSITY REQUIREMENTS:
- Every candidate must represent a meaningfully distinct self-contained moment:
  a different hook, topic, angle, insight, or narrative payoff.
- Do not create multiple candidates that are merely different fragments of the
  same idea or argument.  If two potential candidates cover the same core point,
  keep only the stronger one.
- Do not create near-duplicate candidates with substantially overlapping openings
  or content.
- If only 2 genuinely strong, distinct candidates exist, return 2 rather than
  manufacturing additional candidates.

DISCARD RATHER THAN FORCE:
- If a potential clip cannot satisfy the standalone-opening, complete-thought,
  natural-ending, and contiguous-range requirements without awkward cuts or
  context dependence, you MUST discard it entirely.  Do not include it in the
  output just to fill a slot or reach a duration target.
- Candidate duration (25–90 s) is a target range, not a justification for
  adding unrelated ranges.  A shorter, fully coherent single-range clip is
  always preferable to a longer clip stitched together from disconnected
  sections.

For each candidate you MUST:
- Keep only the portions that deliver real value: hooks, surprises, insights,
  punchy facts, emotional peaks, and natural endings.
- Cut weak openings (filler, channel intros, "today we're going to talk about"),
  unnecessary wording, tangents, dead air descriptions, and low-value padding —
  but only via a tighter single range, not by adding extra jump cuts.

Output ONLY a valid JSON array — no markdown, no prose, no code fences.
Each element of the array must be an object with exactly these keys:

{
  "ranges": [
    {"start": <float seconds>, "end": <float seconds>},
    ...
  ],
  "combined_text": "<text of all kept ranges concatenated with ' [...] ' between gaps>",
  "reason": "<one sentence: why this clip works as a standalone short-form video>",
  "total_duration_s": <sum of (end - start) across all ranges, as a float>,
  "cut_description": "<if multiple ranges: brief note on what was cut and why; otherwise empty string>"
}

Return 1-5 candidates. Prefer fewer, higher-quality candidates. Never pad the
output to reach a quota. Aim for total_duration_s between 25 and 90 per candidate.
"""


def _build_user_message(transcript_text: str, video_id: str) -> str:
    return (
        f"Video ID: {video_id}\n\n"
        "Below is the full timestamped transcript.\n"
        "Select the best clip candidates following the editorial guidelines.\n\n"
        "TRANSCRIPT:\n"
        f"{transcript_text}"
    )


# ---------------------------------------------------------------------------
# Output persistence
# ---------------------------------------------------------------------------


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Public result dataclass
# ---------------------------------------------------------------------------


@dataclass
class ClipperResult:
    """Outcome of a :func:`run_clipper` call."""

    video_id: str
    output_path: Path
    candidates: list[dict]
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_clipper(
    video_id: str,
    *,
    max_llm_retries: int = 2,
    verbose: bool = True,
) -> ClipperResult:
    """Discover clip candidates for *video_id* using LLM editorial analysis.

    Args:
        video_id: The YouTube video ID whose ``en.json`` transcript to load.
        max_llm_retries: How many times to retry if the LLM returns invalid
            JSON or fails schema validation (default 2 = up to 3 total calls).
        verbose: If ``True``, print progress messages to stderr.

    Returns:
        :class:`ClipperResult` with the saved output path and validated
        candidate list.

    Raises:
        FileNotFoundError: Transcript file does not exist.
        RuntimeError: LLM returned invalid output after all retries.
    """
    def _log(msg: str) -> None:
        if verbose:
            print(f"[clipper] {msg}", file=sys.stderr)

    # --- Load transcript ---
    _log(f"Loading transcript for video_id={video_id!r}")
    transcript = _load_transcript(video_id)
    segments: list[dict] = transcript.get("segments", [])
    if not segments:
        raise ValueError(f"Transcript for {video_id!r} contains no segments.")

    duration = _transcript_duration(segments)
    _log(f"Transcript: {len(segments)} segments, duration={duration:.1f}s")

    # --- Format for LLM ---
    transcript_text = _format_transcript_for_llm(segments)

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_message(transcript_text, video_id)},
    ]

    cfg = active_config()
    _log(f"Using LLM: provider={cfg['provider']!r}, model={cfg['model']!r}")

    # --- Call LLM with retries ---
    warnings: list[str] = []
    last_error: str = ""

    for attempt in range(max_llm_retries + 1):
        if attempt > 0:
            _log(f"Retry {attempt}/{max_llm_retries} after validation failure …")

        try:
            raw_output = chat_json(messages, temperature=0.1, max_tokens=4096)
        except (ValueError, EnvironmentError, KeyError, ModuleNotFoundError) as exc:
            raise RuntimeError(f"LLM call failed: {exc}") from exc

        # LLM may return {"candidates": [...]} or directly [...]
        if isinstance(raw_output, dict):
            # Common wrapper keys
            for key in ("candidates", "clips", "results", "output"):
                if key in raw_output and isinstance(raw_output[key], list):
                    raw_output = raw_output[key]
                    break

        errors = _validate_candidates(raw_output, duration)
        if not errors:
            _log(f"Validation passed: {len(raw_output)} candidates")
            candidates = raw_output
            break

        last_error = "\n".join(errors)
        _log(f"Validation errors (attempt {attempt + 1}):\n{last_error}")

        if attempt < max_llm_retries:
            # Feed the errors back to the LLM as a follow-up
            messages.append({"role": "assistant", "content": json.dumps(raw_output)})
            messages.append({
                "role": "user",
                "content": (
                    "Your previous response failed validation. "
                    "Fix ALL of the following errors and return a corrected "
                    "JSON array ONLY:\n\n" + last_error
                ),
            })
    else:
        raise RuntimeError(
            f"LLM returned invalid output after {max_llm_retries + 1} attempt(s).\n"
            f"Last validation errors:\n{last_error}"
        )

    # --- Annotate candidates with derived fields ---
    for cand in candidates:
        ranges = cand["ranges"]
        # Coerce start/end to float and compute total duration
        cand["ranges"] = [
            {"start": float(r["start"]), "end": float(r["end"])} for r in ranges
        ]
        computed_total = sum(r["end"] - r["start"] for r in cand["ranges"])
        cand["total_duration_s"] = round(computed_total, 3)
        # Ensure optional key exists
        cand.setdefault("cut_description", "")

    # --- Save output ---
    output_path = _DOWNLOADS_ROOT / video_id / _OUTPUT_FILENAME
    envelope = {
        "video_id": video_id,
        "llm_provider": cfg["provider"],
        "llm_model": cfg["model"],
        "transcript_duration_s": round(duration, 3),
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    _write_json(output_path, envelope)
    _log(f"Saved {len(candidates)} candidates → {output_path}")

    if warnings:
        for w in warnings:
            _log(f"WARNING: {w}")

    return ClipperResult(
        video_id=video_id,
        output_path=output_path,
        candidates=candidates,
        warnings=warnings,
    )
