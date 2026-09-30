#!/usr/bin/env python3
import json
import os
import sys

def load_json(path):
    with open(path, 'r') as f:
        return json.load(f)

def main():
    # Parse arguments: VIDEO_ID [--candidate-id N]
    if len(sys.argv) < 2 or len(sys.argv) > 4:
        print(f"Usage: {sys.argv[0]} VIDEO_ID [--candidate-id N]")
        sys.exit(1)
    video_id = sys.argv[1]
    candidate_id = 1  # default for backward compatibility
    if len(sys.argv) == 4:
        if sys.argv[2] == '--candidate-id':
            try:
                candidate_id = int(sys.argv[3])
            except ValueError:
                print(f"Error: --candidate-id must be an integer")
                sys.exit(1)
        else:
            print(f"Usage: {sys.argv[0]} VIDEO_ID [--candidate-id N]")
            sys.exit(1)
    elif len(sys.argv) == 3:
        print(f"Usage: {sys.argv[0]} VIDEO_ID [--candidate-id N]")
        sys.exit(1)

    base_dir = f'/root/youtubr_clipper/media/downloads/{video_id}'
    final_clip_timings = load_json(os.path.join(base_dir, 'final_clip_timings.json'))
    caption_manifest = load_json(os.path.join(base_dir, 'caption_manifest.json'))
    broll_manifest = load_json(os.path.join(base_dir, 'broll_manifest.json'))

    # Extract data for selected candidate
    cand_data = None
    for cand in final_clip_timings['candidates']:
        if cand['candidate_id'] == candidate_id:
            cand_data = cand
            break
    if cand_data is None:
        raise ValueError(f"Candidate {candidate_id} not found")

    total_duration = cand_data['total_clip_duration_s']
    clip_relative_ranges = cand_data['clip_relative_ranges']
    aligned_words = cand_data['aligned_words']

    # Get caption groups for selected candidate
    caption_groups = None
    for cand in caption_manifest['candidates']:
        if cand['candidate_id'] == candidate_id:
            caption_groups = cand['caption_groups']
            break
    if caption_groups is None:
        raise ValueError(f"Caption groups for candidate {candidate_id} not found")

    # Get broll visual decisions for selected candidate
    broll_data = None
    for cand in broll_manifest['candidates']:
        if cand['candidate_id'] == candidate_id:
            broll_data = cand
            break
    if broll_data is None:
        raise ValueError(f"Broll data for candidate {candidate_id} not found")
    visual_decisions = broll_data['visual_decisions']

    # --- Speech regions from caption groups (merge overlapping?) ---
    speech_regions = []
    for group in caption_groups:
        speech_regions.append({
            'start': group['start_time'],
            'end': group['end_time'],
            'text': group['text']
        })

    # Optional: merge overlapping or adjacent speech regions (if needed)
    # We'll keep as is.

    # --- Background music: one track spanning whole clip, with ducking during speech ---
    background_music = [{
        'start': 0.0,
        'end': total_duration,
        'volume': 0.3,  # base volume for music
        'ducking': True
    }]

    # --- Speech ducking: reduce music volume during speech ---
    speech_ducking = []
    for region in speech_regions:
        speech_ducking.append({
            'start': region['start'],
            'end': region['end'],
            'duck_amount': 0.7  # reduce music volume by 70% (i.e., music at 30% * (1-0.7) = 0.09 during speech)
        })

    # --- SFX placement ---
    sfx_events = []

    # 1. SFX at visual decision boundaries (start and end of each visual decision)
    for vd in visual_decisions:
        auth_timing = vd['authoritative_timing']
        start_time = auth_timing['clip_start']
        end_time = auth_timing['clip_end']
        # Add a subtle SFX at start and end (e.g., a soft whoosh or click)
        sfx_events.append({
            'time': start_time,
            'type': 'whoosh_in',
            'description': f"SFX at start of {vd['decision']} segment: {vd['supported_phrase'][:30]}...",
            'volume': 0.4
        })
        sfx_events.append({
            'time': end_time,
            'type': 'whoosh_out',
            'description': f"SFX at end of {vd['decision']} segment: {vd['supported_phrase'][:30]}...",
            'volume': 0.4
        })

    # 2. SFX at high-emphasis words (alignment score > 0.9)
    for word in aligned_words:
        if word['score'] > 0.9:
            sfx_events.append({
                'time': word['clip_start'],
                'type': 'click',
                'description': f"Emphasis on word '{word['word']}' (score {word['score']:.2f})",
                'volume': 0.3
            })

    # 3. SFX at transitions between clip_relative_ranges (if any gaps? but ranges are contiguous)
    # Actually clip_relative_ranges are contiguous and cover whole clip, so no gaps.

    # Sort SFX by time and deduplicate (if same time, combine? we'll keep separate)
    sfx_events.sort(key=lambda x: x['time'])

    # Limit SFX count to avoid too many (optional)
    # We'll keep all for now.

    # Build manifest
    manifest = {
        'video_id': final_clip_timings['video_id'],
        'selected_candidate_id': candidate_id,
        'total_clip_duration_s': total_duration,
        'background_music': background_music,
        'speech_ducking': speech_ducking,
        'sfx': sfx_events
    }

    # Write manifest to file (candidate-specific)
    output_path = os.path.join(base_dir, f'audio_planning_manifest_cand{candidate_id}.json')
    with open(output_path, 'w') as f:
        json.dump(manifest, f, indent=2)

    print(f"Audio planning manifest written to {output_path}")
    print(f"Summary:")
    print(f"  Total duration: {total_duration:.2f}s")
    print(f"  Background music tracks: {len(background_music)}")
    print(f"  Speech ducking regions: {len(speech_ducking)}")
    print(f"  SFX events: {len(sfx_events)}")
    if sfx_events:
        print(f"  First few SFX: {sfx_events[:3]}")

if __name__ == '__main__':
    main()