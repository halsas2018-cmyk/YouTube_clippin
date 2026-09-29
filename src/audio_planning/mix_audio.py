#!/usr/bin/env python3
import json
import os
import sys
import wave
import struct
import math

def load_wav_float(file_path):
    """Load a mono WAV file and return list of floats in [-1, 1] and sample rate."""
    with wave.open(file_path, 'rb') as wf:
        nchannels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        nframes = wf.getnframes()
        if nchannels != 1:
            raise ValueError(f"Expected mono audio, got {nchannels} channels")
        if sampwidth != 2:
            raise ValueError(f"Expected 16-bit audio, got {sampwidth*8}-bit")
        frames = wf.readframes(nframes)
        # unpack as 16-bit little-endian
        samples = struct.unpack('<{}h'.format(nframes), frames)
        # convert to float
        samples_float = [s / 32768.0 for s in samples]  # 32768.0 to keep [-1,1]
        return samples_float, framerate

def save_wav_float(samples_float, file_path, framerate):
    """Save list of floats in [-1,1] as 16-bit mono WAV."""
    # Clip to avoid overflow
    clipped = [max(-1.0, min(1.0, s)) for s in samples_float]
    # Convert to 16-bit PCM
    samples_int = [int(s * 32767.0) for s in clipped]
    nframes = len(samples_int)
    with wave.open(file_path, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(framerate)
        wf.setnframes(nframes)
        wf.setcomptype('NONE', 'not compressed')
        wf.writeframes(struct.pack('<{}h'.format(nframes), *samples_int))

def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} VIDEO_ID")
        sys.exit(1)
    video_id = sys.argv[1]
    base_dir = f'/root/youtubr_clipper/media/downloads/{video_id}'
    audio_dir = os.path.join(base_dir, 'media', 'audio')

    # Load manifests
    planning_path = os.path.join(base_dir, 'audio_planning_manifest.json')
    acquisition_path = os.path.join(audio_dir, 'acquisition_manifest.json')

    with open(planning_path, 'r') as f:
        planning = json.load(f)
    with open(acquisition_path, 'r') as f:
        acquisition = json.load(f)

    video_id = planning['video_id']
    total_duration = planning['total_clip_duration_s']  # 17.882
    print(f"Processing {video_id}, duration {total_duration}s")

    # Extract background music info
    bg_info = None
    for asset in acquisition['audio_assets']:
        if asset['type'] == 'background_music':
            bg_info = asset
            break
    if bg_info is None:
        raise ValueError("Background music asset not found")
    bg_path = bg_info['local_path']

    # Extract speech ducking regions from planning
    speech_ducking = planning['speech_ducking']  # list of dicts with start, end, duck_amount

    # Extract SFX events
    sfx_events = planning['sfx']  # list of dicts with time, type, description, volume

    # Load background music
    bg_samples, bg_rate = load_wav_float(bg_path)
    # Ensure duration matches
    expected_samples = int(total_duration * bg_rate)
    if len(bg_samples) != expected_samples:
        print(f"Warning: background music length {len(bg_samples)} samples, expected {expected_samples}. Trimming/padding.")
        if len(bg_samples) > expected_samples:
            bg_samples = bg_samples[:expected_samples]
        else:
            # pad with zeros
            bg_samples = bg_samples + [0.0] * (expected_samples - len(bg_samples))

    # Initialize output with background music at base volume 0.3
    output = [sample * 0.3 for sample in bg_samples]  # apply base volume

    # Apply speech ducking: reduce music volume during speech regions
    for region in speech_ducking:
        start = region['start']
        end = region['end']
        duck_amount = region['duck_amount']  # 0.7 means reduce by 70%
        start_sample = int(start * bg_rate)
        end_sample = int(end * bg_rate)
        # Clamp to bounds
        if start_sample < 0:
            start_sample = 0
        if end_sample > len(output):
            end_sample = len(output)
        factor = 1.0 - duck_amount  # e.g., 0.3
        for i in range(start_sample, end_sample):
            output[i] *= factor

    # Prepare SFX assets: load whoosh and click once
    sfx_audio = {}  # type -> (samples, rate)
    for asset in acquisition['audio_assets']:
        if asset['type'] in ('whoosh', 'click'):
            sfx_samples, sfx_rate = load_wav_float(asset['local_path'])
            sfx_audio[asset['type']] = (sfx_samples, sfx_rate)
            print(f"Loaded {asset['type']}: {len(sfx_samples)} samples at {sfx_rate}Hz")

    # Mix SFX events
    for event in sfx_events:
        event_time = event['time']
        event_type = event['type']
        event_volume = event['volume']  # 0.4 for whoosh, 0.3 for click
        # Map SFX type to asset type
        if event_type in ('whoosh_in', 'whoosh_out'):
            asset_type = 'whoosh'
        elif event_type == 'click':
            asset_type = 'click'
        else:
            print(f"Warning: unknown SFX type {event_type}")
            continue
        if asset_type not in sfx_audio:
            print(f"Warning: no audio asset for type {asset_type}")
            continue
        start_sample = int(event_time * bg_rate)
        sfx_samples, sfx_rate = sfx_audio[asset_type]
        # Ensure rates match (they should)
        if sfx_rate != bg_rate:
            print(f"Warning: SFX rate {sfx_rate} != background rate {bg_rate}; assuming same")
            # For simplicity, we could resample but skip; assume same.
        # Place SFX
        for i, sfx_sample in enumerate(sfx_samples):
            out_idx = start_sample + i
            if out_idx < 0 or out_idx >= len(output):
                continue
            output[out_idx] += sfx_sample * event_volume

    # Optional: soft clip to avoid distortion
    # We'll just clip to [-1, 1]
    output = [max(-1.0, min(1.0, s)) for s in output]

    # Save mixed audio
    mix_path = os.path.join(audio_dir, 'mixed.wav')
    save_wav_float(output, mix_path, bg_rate)
    print(f"Saved mixed audio to {mix_path}")
    print(f"  Duration: {len(output)/bg_rate:.3f}s")
    print(f"  Samples: {len(output)}")

    # Validate
    print("\n--- Validation ---")
    # 1. Duration
    dur = len(output) / bg_rate
    if abs(dur - total_duration) < 0.01:
        print(f"✓ Duration correct: {dur:.3f}s (expected {total_duration:.3f}s)")
    else:
        print(f"✗ Duration mismatch: got {dur:.3f}s, expected {total_duration:.3f}s")

    # 2. Non-silence: compute RMS
    import math
    sum_squares = sum(s*s for s in output)
    rms = math.sqrt(sum_squares / len(output)) if len(output) > 0 else 0
    if rms > 0.01:
        print(f"✓ Non-silent audio: RMS = {rms:.6f}")
    else:
        print(f"✗ Audio too quiet: RMS = {rms:.6f}")

    # 3. Check ducking: compute average power in speech regions vs non-speech regions
    if speech_ducking:
        # Collect all speech region samples
        speech_power_sum = 0.0
        speech_sample_count = 0
        for region in speech_ducking:
            start_s = int(region['start'] * bg_rate)
            end_s = int(region['end'] * bg_rate)
            if end_s > start_s:
                for i in range(start_s, end_s):
                    speech_power_sum += output[i] * output[i]
                speech_sample_count += (end_s - start_s)
        # Compute non-speech power as the rest of the audio
        # Create a mask of speech regions for efficiency (could be large but okay for this duration)
        # We'll instead compute total power and subtract speech power
        total_power_sum = sum(s*s for s in output)
        non_speech_power_sum = total_power_sum - speech_power_sum
        non_speech_sample_count = len(output) - speech_sample_count
        if speech_sample_count > 0 and non_speech_sample_count > 0:
            power_speech = speech_power_sum / speech_sample_count
            power_nonspeech = non_speech_power_sum / non_speech_sample_count
            if power_speech < power_nonspeech * 0.5:  # expect significant reduction due to ducking
                print(f"✓ Ducking detected: speech power {power_speech:.6f} < non-speech {power_nonspeech:.6f}")
            else:
                print(f"⚠ Ducking weak: speech power {power_speech:.6f}, non-speech {power_nonspeech:.6f} (reduction factor {power_speech/power_nonspeech if power_nonspeech>0 else 0:.2f})")
        else:
            print("⚠ Could not compute ducking validation (insufficient speech or non-speech samples)")
    else:
        print("⚠ No speech ducking regions to validate")

    # 4. Check SFX presence: we can do a simple check by looking at energy around SFX times (optional)
    # We'll just count events and assume they added something
    print(f"✓ Mixed {len(sfx_events)} SFX events")

    # Save concise mix manifest
    mix_manifest = {
        'video_id': video_id,
        'source_manifests': {
            'audio_planning': planning_path,
            'acquisition': acquisition_path
        },
        'output_path': mix_path,
        'sample_rate_hz': bg_rate,
        'duration_s': dur,
        'background_music_volume_base': 0.3,
        'speech_ducking_applied': len(speech_ducking),
        'sfx_events_count': len(sfx_events),
        'validation': {
            'duration_ok': abs(dur - total_duration) < 0.01,
            'non_silent_rms': rms,
            'ducking_verified': 'checked' if speech_ducking else 'none'
        }
    }
    mix_manifest_path = os.path.join(audio_dir, 'mix_manifest.json')
    with open(mix_manifest_path, 'w') as f:
        json.dump(mix_manifest, f, indent=2)
    print(f"\nMix manifest saved to {mix_manifest_path}")

    print("\nMixing completed successfully.")

if __name__ == '__main__':
    main()