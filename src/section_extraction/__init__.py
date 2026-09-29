"""Section extraction stage: identify moments from transcripts and extract padded sections."""
from .extractor import (
    SectionMetadata,
    download_section_range,
    extract_sections,
    get_ytdlp_binary,
    probe_media_duration,
    probe_media_info,
)
from .range_padding import (
    DEFAULT_OUTPUT_FILENAME,
    DEFAULT_PADDING_SECONDS,
    TimeRange,
    get_video_duration,
    merge_overlapping_ranges,
    pad_and_merge_ranges,
    pad_candidate,
    pad_candidates,
    pad_single_range,
    process_clip_candidates,
    run_range_padding,
)

__all__ = [
    "DEFAULT_OUTPUT_FILENAME",
    "DEFAULT_PADDING_SECONDS",
    "SectionMetadata",
    "TimeRange",
    "download_section_range",
    "extract_sections",
    "get_video_duration",
    "get_ytdlp_binary",
    "merge_overlapping_ranges",
    "pad_and_merge_ranges",
    "pad_candidate",
    "pad_candidates",
    "pad_single_range",
    "probe_media_duration",
    "probe_media_info",
    "process_clip_candidates",
    "run_range_padding",
]
