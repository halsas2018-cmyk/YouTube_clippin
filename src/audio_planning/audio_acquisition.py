#!/usr/bin/env python3
import json
import os
import requests
import sys
from pathlib import Path

def load_json(path):
    with open(path, 'r') as f:
        return json.load(f)

def save_json(data, path):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

def download_audio(api_key, query, save_path):
    """
    Download an audio file from Pixabay based on query.
    Returns (success, file_size, source_url, license_info) or (False, None, None, None) on failure.
    """
    url = "https://pixabay.com/api/audio/"
    params = {
        'key': api_key,
        'q': query,
        'per_page': 3,  # get a few results to choose from
        'safesearch': 'true'
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data['totalHits'] == 0:
            print(f"No results found for query: {query}")
            return False, None, None, None
        # Take the first result
        hit = data['hits'][0]
        audio_url = hit['url']  # direct link to MP3
        license_info = hit.get('license', 'unknown')
        # Download the audio file
        audio_response = requests.get(audio_url, timeout=15)
        audio_response.raise_for_status()
        with open(save_path, 'wb') as f:
            f.write(audio_response.content)
        file_size = os.path.getsize(save_path)
        return True, file_size, audio_url, license_info
    except Exception as e:
        print(f"Error downloading audio for query '{query}': {e}")
        return False, None, None, None

def main():
    # Paths
    base_dir = '/root/youtubr_clipper/media/downloads/FltNsyPXNdo'
    manifest_path = '/root/youtubr_clipper/src/audio_planning/audio_planning_manifest.json'
    audio_dir = os.path.join(base_dir, 'media', 'audio')
    os.makedirs(audio_dir, exist_ok=True)

    # Load audio planning manifest
    manifest = load_json(manifest_path)
    video_id = manifest['video_id']
    total_duration = manifest['total_clip_duration_s']
    sfx_events = manifest['sfx']

    # Determine unique audio assets needed
    # Background music: one track
    # SFX types: whoosh_in, whoosh_out -> map to 'whoosh'; click -> 'click'
    audio_types_needed = {
        'background_music': {'query': 'ambient background music', 'count': 1},
        'whoosh': {'query': 'whoosh sound effect', 'count': 1},  # used for both in and out
        'click': {'query': 'click sound effect', 'count': 1}
    }

    # Pixabay API key from environment
    api_key = os.environ.get('PIXABAY_API_KEY')
    if not api_key:
        # Try to read from .env file
        env_path = '/root/youtubr_clipper/.env'
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                for line in f:
                    if line.startswith('PIXABAY_API_KEY='):
                        api_key = line.strip().split('=', 1)[1].strip('"')
                        break
        if not api_key:
            print("Error: PIXABAY_API_KEY not found in environment or .env file")
            sys.exit(1)

    # Acquisition manifest structure
    acquisition_manifest = {
        'video_id': video_id,
        'total_clip_duration_s': total_duration,
        'audio_assets': [],
        'acquisition_summary': {
            'acquired': 0,
            'failed': 0,
            'skipped': 0,
            'total_attempted': 0
        }
    }

    # Process each audio type
    for asset_type, info in audio_types_needed.items():
        acquisition_manifest['acquisition_summary']['total_attempted'] += 1
        # Define expected local path
        if asset_type == 'background_music':
            filename = 'background_music.mp3'
        elif asset_type == 'whoosh':
            filename = 'whoosh.mp3'
        elif asset_type == 'click':
            filename = 'click.mp3'
        else:
            continue
        local_path = os.path.join(audio_dir, filename)

        # Check if file already exists and is non-empty (idempotent)
        if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
            print(f"Skipping {asset_type}: {local_path} already exists")
            acquisition_manifest['acquisition_summary']['skipped'] += 1
            # Still add to acquisition manifest for completeness
            asset_record = {
                'asset_id': f"audio_{asset_type}_001",
                'type': asset_type,
                'local_path': local_path,
                'source_url': 'local_file_previously_acquired',
                'provider': 'pixabay',  # assume it was from pixabay if exists
                'license': 'unknown',  # we don't have license info for existing file
                'query': info['query'],
                'timing': {
                    'start': 0.0 if asset_type == 'background_music' else None,
                    'end': total_duration if asset_type == 'background_music' else None
                }
            }
            acquisition_manifest['audio_assets'].append(asset_record)
            continue

        # Attempt to download
        print(f"Acquiring {asset_type} with query: '{info['query']}'")
        success, file_size, source_url, license_info = download_audio(
            api_key, info['query'], local_path
        )
        if success:
            print(f"Successfully acquired {asset_type}: {local_path} ({file_size} bytes)")
            acquisition_manifest['acquisition_summary']['acquired'] += 1
            asset_record = {
                'asset_id': f"audio_{asset_type}_001",
                'type': asset_type,
                'local_path': local_path,
                'source_url': source_url,
                'provider': 'pixabay',
                'license': license_info,
                'query': info['query'],
                'timing': {
                    'start': 0.0 if asset_type == 'background_music' else None,
                    'end': total_duration if asset_type == 'background_music' else None
                }
            }
            acquisition_manifest['audio_assets'].append(asset_record)
        else:
            print(f"Failed to acquire {asset_type}")
            acquisition_manifest['acquisition_summary']['failed'] += 1
            # Still add a record for the failed asset? We'll skip adding to audio_assets for failed.

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
    sys.exit(0 if validation_passed else 1)

if __name__ == '__main__':
    main()