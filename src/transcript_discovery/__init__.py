"""Transcript / candidate discovery stage — LLM-based clip selection.

Public API::

    from src.transcript_discovery import run_clipper, ClipperResult
"""
from .clipper import ClipperResult, run_clipper

__all__ = ["ClipperResult", "run_clipper"]
