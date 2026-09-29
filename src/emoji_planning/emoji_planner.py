#!/usr/bin/env python3
"""
LLM-based emoji planning stage for selecting meaningful words/phrases to enhance with emojis.
Consumes existing caption_manifest.json and produces emoji_manifest.json.
Uses the existing src/transcript_discovery/llm_client.py for LLM communication.
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Any

# Add the src directory to the path so we can import transcript_discovery
sys.path.append(str(Path(__file__).resolve().parents[1]))

from transcript_discovery.llm_client import chat_json


def load_caption_manifest(video_id: str) -> Dict[str, Any]:
    """Load the existing caption manifest for the given video."""
    manifest_path = Path(f"/root/youtubr_clipper/media/downloads/{video_id}/caption_manifest.json")
    with open(manifest_path, 'r') as f:
        return json.load(f)


def extract_caption_text_for_llm(caption_groups: List[Dict]) -> str:
    """
    Extract caption text in a format suitable for LLM processing.
    Returns a clean text representation preserving word order and grouping.
    """
    text_parts = []
    for group in caption_groups:
        # Reconstruct the text from words, preserving spacing
        group_text = "".join([word["word"] for word in group["words"]])
        text_parts.append(group_text.strip())
    return " ".join(text_parts)


def build_emoji_prompt(caption_text: str, video_id: str, candidate_id: int) -> List[Dict[str, str]]:
    """
    Build the prompt for the LLM to select words/phrases for emoji enhancement.
    """
    system_message = {
        "role": "system",
        "content": """You are an emoji selection specialist for video captions. Your task is to identify meaningful/emphatic words or short phrases in the caption text that would benefit from an emoji enhancement for better visual engagement in short-form video content.

Rules:
1. Select ONLY words or short phrases (max 3 words) that are genuinely emphatic, emotional, or meaningful
2. Be conservative - select at most 5-7 emoji enhancements per candidate to avoid clutter
3. Choose emojis that clearly relate to the meaning or emotion of the word/phrase
4. Return ONLY valid JSON in the specified format
5. Do not modify the original text or add timestamps
6. Focus on content words (nouns, verbs, adjectives, adverbs) rather than function words

Return JSON with this exact structure:
{
  "emoji_selections": [
    {
      "text": "exact word or phrase as it appears in caption",
      "emoji": "single emoji character",
      "reason": "brief explanation why this word/phrase was selected"
    }
  ]
}"""

    }

    user_message = {
        "role": "user",
        "content": f"""Video ID: {video_id}
Candidate ID: {candidate_id}

Caption text to analyze:
"{caption_text}"

Select meaningful words/phrases for emoji enhancement following the rules above."""
    }

    return [system_message, user_message]


def create_emoji_manifest(caption_data: Dict[str, Any], llm_selections: List[Dict]) -> Dict[str, Any]:
    """
    Create the emoji manifest that maps LLM selections to actual caption word timings.
    """
    emoji_manifest = {
        "video_id": caption_data["video_id"],
        "llm_provider": caption_data.get("llm_provider", "unknown"),
        "llm_model": caption_data.get("llm_model", "unknown"),
        "candidates": []
    }

    # Find candidate 1 data
    candidate_data = None
    for candidate in caption_data["candidates"]:
        if candidate["candidate_id"] == 1:
            candidate_data = candidate
            break

    if not candidate_data:
        raise ValueError("Candidate 1 not found in caption data")

    # Build a lookup map for quick word matching
    word_lookup = {}
    for group_idx, group in enumerate(candidate_data["caption_groups"]):
        for word_idx, word in enumerate(group["words"]):
            # Key by cleaned word text (lowercase, no punctuation) for matching
            clean_text = word["word"].lower().strip(".,!?;:")
            word_lookup[clean_text] = {
                "group_index": group_idx,
                "word_index": word_idx,
                "group_id": group["group_id"],
                "clip_start": word["clip_start"],
                "clip_end": word["clip_end"],
                "original_text": word["word"],
                "start_time": group["start_time"],
                "end_time": group["end_time"]
            }

    # Process LLM selections
    emoji_entries = []
    for selection in llm_selections:
        text = selection["text"].strip()
        emoji = selection["emoji"].strip()
        reason = selection.get("reason", "")

        # Clean the selection text for matching
        clean_selection = text.lower().strip(".,!?;:")

        # Handle multi-word phrases by checking if all words exist consecutively
        words_in_selection = clean_selection.split()
        matched = False

        # Try to find exact phrase match first
        if clean_selection in word_lookup:
            word_info = word_lookup[clean_selection]
            emoji_entries.append({
                "text": text,
                "emoji": emoji,
                "reason": reason,
                "group_id": word_info["group_id"],
                "clip_start": word_info["clip_start"],
                "clip_end": word_info["clip_end"],
                "start_time": word_info["start_time"],
                "end_time": word_info["end_time"],
                "matched_text": word_info["original_text"]
            })
            matched = True
        else:
            # Try to find consecutive word match for phrases
            # Flatten all words for phrase matching
            all_words = []
            word_positions = []  # track (group_idx, word_idx) for each word
            for g_idx, group in enumerate(candidate_data["caption_groups"]):
                for w_idx, word in enumerate(group["words"]):
                    clean_word = word["word"].lower().strip(".,!?;:")
                    all_words.append(clean_word)
                    word_positions.append((g_idx, w_idx, word["word"], word["clip_start"], word["clip_end"], group["start_time"], group["end_time"], group["group_id"]))

            # Check if our phrase matches starting at this position
            for start_idx in range(len(all_words) - len(words_in_selection) + 1):
                match_found = True
                for i, sel_word in enumerate(words_in_selection):
                    if all_words[start_idx + i] != sel_word:
                        match_found = False
                        break

                if match_found:
                    # Use the first word's timing for the phrase (conservative approach)
                    first_word_info = word_positions[start_idx]
                    emoji_entries.append({
                        "text": text,
                        "emoji": emoji,
                        "reason": reason,
                        "group_id": first_word_info[7],
                        "clip_start": first_word_info[3],
                        "clip_end": first_word_info[4],
                        "start_time": first_word_info[5],
                        "end_time": first_word_info[6],
                        "matched_text": " ".join([wp[2] for wp in word_positions[start_idx:start_idx+len(words_in_selection)]])
                    })
                    matched = True
                    break

        if not matched:
            # Log unmatched selections for debugging (but don't fail)
            print(f"Warning: Could not match emoji selection '{text}' to caption words")

    emoji_manifest["candidates"] = [{
        "candidate_id": 1,
        "total_clip_duration_s": candidate_data["total_clip_duration_s"],
        "emoji_selections": emoji_entries
    }]

    return emoji_manifest


def main():
    """Main execution function."""
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} VIDEO_ID")
        sys.exit(1)
    video_id = sys.argv[1]

    print(f"Loading caption manifest for {video_id}...")
    caption_data = load_caption_manifest(video_id)

    # Find candidate 1
    candidate_data = None
    for candidate in caption_data["candidates"]:
        if candidate["candidate_id"] == 1:
            candidate_data = candidate
            break

    if not candidate_data:
        raise ValueError("Candidate 1 not found")

    print("Extracting caption text for LLM analysis...")
    # Fix: use "word" field instead of "text" for individual words
    caption_text_parts = []
    for group in candidate_data["caption_groups"]:
        # Reconstruct the text from words, preserving spacing
        group_text = "".join([word["word"] for word in group["words"]])
        caption_text_parts.append(group_text.strip())
    caption_text = " ".join(caption_text_parts)
    print(f"Caption text: {caption_text[:100]}...")

    print("Building LLM prompt...")
    messages = build_emoji_prompt(caption_text, video_id, 1)

    print("Calling LLM for emoji selection...")
    try:
        llm_response = chat_json(messages)
        print(f"LLM response: {llm_response}")

        # Extract emoji selections
        if isinstance(llm_response, dict) and "emoji_selections" in llm_response:
            llm_selections = llm_response["emoji_selections"]
        elif isinstance(llm_response, list):
            llm_selections = llm_response
        else:
            llm_selections = []

        print(f"LLM selected {len(llm_selections)} emoji enhancements")

    except Exception as e:
        print(f"LLM call failed: {e}")
        print("Using empty selections as fallback")
        llm_selections = []

    print("Creating emoji manifest...")
    emoji_manifest = create_emoji_manifest(caption_data, llm_selections)

    # Save emoji manifest
    output_dir = Path(f"/root/youtubr_clipper/media/downloads/{video_id}")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "emoji_manifest.json"

    with open(output_path, 'w') as f:
        json.dump(emoji_manifest, f, indent=2)

    print(f"Emoji manifest saved to {output_path}")
    print(f"Total emoji selections: {len(emoji_manifest['candidates'][0]['emoji_selections'])}")

    # Print selections for verification
    for selection in emoji_manifest["candidates"][0]["emoji_selections"]:
        print(f"  - '{selection['text']}' → {selection['emoji']} ({selection['reason']})")


if __name__ == "__main__":
    main()