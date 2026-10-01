#!/usr/bin/env python3
import sys
sys.path.insert(0, '/root/youtubr_clipper/src')
from section_extraction.extractor import extract_sections
sections = extract_sections('S-7VkwSU0gs', overwrite=True)
for s in sections:
    print(f'[{s.section_id}] {s.file_name}: offset {s.start_offset:.2f}s -> {s.end_offset:.2f}s (target {s.target_duration_s:.2f}s, probed {s.probed_duration_s:.2f}s)')