#!/usr/bin/env python3
import json
import os
import sys
import wave
import struct
import math
from pathlib import Path

def create_silent_wav(file_path, duration_seconds, sample_rate=44100, amplitude=0.1):
    """Create a placeholder WAV file with audible tone."""
    # Ensure directory exists
    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    # WAV file parameters
    nchannels = 1          # mono
    sampwidth = 2          # 16-bit
    comptype = "NONE"
    compname = "not compressed"
    nframes = int(duration_seconds * sample_rate)

    with wave.open(file_path, 'w') as wav_file:
        wav_file.setparams((nchannels, sampwidth, sample_rate, nframes, comptype, compname))
        # Generate a simple audible tone (440 Hz sine wave) instead of silence
        for i in range(nframes):
            # Generate a 440 Hz sine wave
            t = i / sample_rate  # time in seconds
            sample_value = int(amplitude * 32767 * math.sin(2 * math.pi * 440 * t))
            wav_file.writeframes(struct.pack('<h', sample_value))

    return os.path.getsize(file_path)

def load_json(path):
    with open(path, 'r') as f:
        return json.load(f)

def save_json(data, path):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

def main():
    if len(sys.argv) < 2 or len(sys.argv) > 3:
        print(f"Usage: {sys.argv[0]} VIDEO_ID [--force]")
        sys.exit(1)
    video_id = sys.argv[1]
    force_regenerate = False
    if len(sys.argv) == 3:
        if sys.argv[2] == "--force":
            force_regenerate = True
        else:
            print(f"Usage: {sys.argv[0]} VIDEO_ID [--force]")
            sys.exit(1)
    # Paths
    base_dir = f'/root/youtubr_clipper/media/downloads/{video_id}'
    manifest_path = os.path.join(base_dir, 'audio_planning_manifest.json')
    audio_dir = os.path.join(base_dir, 'media', 'audio')
    os.makedirs(audio_dir, exist_ok=True)

    # Load audio planning manifest
    manifest = load_json(manifest_path)
    video_id = manifest['video_id']
    total_duration = manifest['total_clip_duration_s']
    sfx_events = manifest['sfx']

    # Determine unique audio assets needed
    # Background music: one track (full duration)
    # SFX types: whoosh_in, whoosh_out -> map to 'whoosh'; click -> 'click'
    audio_types_needed = {
        'background_music': {'duration': total_duration, 'description': 'Background music track'},
        'whoosh': {'duration': 0.5, 'description': 'Whoosh sound effect'},  # reasonable duration for whoosh
        'click': {'duration': 0.1, 'description': 'Click sound effect'}   # short click
    }

    # Acquisition manifest structure
    acquisition_manifest = {
        'video_id': video_id,
        'total_clip_duration_s': total_duration,
        'audio_assets': [],
        'acquisition_summary': {
            'acquired': 0,
            'failed': 0,
            'skipped': 0,
            'total_attempted': len(audio_types_needed)
        }
    }

    # Process each audio type
    for asset_type, info in audio_types_needed.items():
        acquisition_manifest['acquisition_summary']['total_attempted'] += 0  # already counted above
        # Define expected local path
        if asset_type == 'background_music':
            filename = 'background_music.wav'
        elif asset_type == 'whoosh':
            filename = 'whoosh.wav'
        elif asset_type == 'click':
            filename = 'click.wav'
        else:
            continue
        local_path = os.path.join(audio_dir, filename)

        # Check if file already exists and is non-empty (idempotent)
        if os.path.exists(local_path) and os.path.getsize(local_path) > 0 and not force_regenerate:
            print(f"Skipping {asset_type}: {local_path} already exists")
            acquisition_manifest['acquisition_summary']['skipped'] += 1
            # Still add to acquisition manifest for completeness
            asset_record = {
                'asset_id': f"audio_{asset_type}_001",
                'type': asset_type,
                'local_path': local_path,
                'source_url': 'local_file_previously_acquired',
                'provider': 'placeholder',  # indicate it's a placeholder
                'license': 'placeholder',
                'query': info['description'],
                'timing': {
                    'start': 0.0 if asset_type == 'background_music' else None,
                    'end': total_duration if asset_type == 'background_music' else None
                }
            }
            acquisition_manifest['audio_assets'].append(asset_record)
            continue

        # Create silent WAV file as placeholder
        print(f"Creating placeholder {asset_type} ({info['duration']}s duration)")
        try:
            file_size = create_silent_wav(local_path, info['duration'])
            print(f"Successfully created {asset_type}: {local_path} ({file_size} bytes)")
            acquisition_manifest['acquisition_summary']['acquired'] += 1
            asset_record = {
                'asset_id': f"audio_{asset_type}_001",
                'type': asset_type,
                'local_path': local_path,
                'source_url': f'placeholder://{asset_type}',
                'provider': 'placeholder',
                'license': 'placeholder (silent audio for validation)',
                'query': info['description'],
                'timing': {
                    'start': 0.0 if asset_type == 'background_music' else None,
                    'end': total_duration if asset_type == 'background_music' else None
                }
            }
            acquisition_manifest['audio_assets'].append(asset_record)
        except Exception as e:
            print(f"Failed to create {asset_type}: {e}")
            acquisition_manifest['acquisition_summary']['failed'] += 1

    # Save acquisition manifest
    acquisition_manifest_path = os.path.join(audio_dir, 'acquisition_manifest.json')
    save_json(acquisition_manifest, acquisition_manifest_path)
    print(f"\nAcquisition manifest saved to: {acquisition_manifest_path}")

    # Validation: ensure every SFX event has a corresponding audio asset
    print("\n--- Validation ---")
    validation_passed = True
    # Map SFX types to asset types
    sfx_to_asset = {
        'whoosh_in': 'whoosh',
        'whoosh_out': 'whoosh',
        'click': 'click'
    }
    # Check that required assets exist
    asset_exists = {}
    for asset in acquisition_manifest['audio_assets']:
        asset_exists[asset['type']] = os.path.exists(asset['local_path']) and os.path.getsize(asset['local_path']) > 0

    # Background music validation (just check it exists)
    if 'background_music' in asset_exists and asset_exists['background_music']:
        print("✓ Background music asset exists")
    else:
        print("✗ Background music asset missing")
        validation_passed = False

    # Validate each SFX event
    for i, event in enumerate(sfx_events):
        event_type = event['type']
        required_asset_type = sfx_to_asset.get(event_type)
        if not required_asset_type:
            print(f"✗ Unknown SFX type in event {i}: {event_type}")
            validation_passed = False
            continue
        if asset_exists.get(required_asset_type, False):
            # We could also check that the asset is suitable, but we just check existence
            pass
        else:
            print(f"✗ SFX event {i} (type: {event_type}) requires asset '{required_asset_type}' which is missing")
            validation_passed = False

    if validation_passed:
        print("✓ All validation checks passed")
    else:
        print("✗ Some validation checks failed")

    # Print summary
    summary = acquisition_manifest['acquisition_summary']
    print(f"\nAcquisition Summary:")
    print(f"  Acquired: {summary['acquired']}")
    print(f"  Failed: {summary['failed']}")
    print(f"  Skipped: {summary['skipped']}")
    print(f"  Total Attempted: {summary['total_attempted']}")

    print(f"\nAudio assets saved to: {audio_dir}")
    for asset in acquisition_manifest['audio_assets']:
        print(f"  - {asset['type']}: {asset['local_path']}")

    # Exit with appropriate code
    exit(0 if validation_passed else 1)

if __name__ == '__main__':
    main()