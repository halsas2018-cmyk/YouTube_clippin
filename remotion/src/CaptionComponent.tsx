import React, { useState, useEffect, useCallback } from "react";
import {
  AbsoluteFill,
  staticFile,
  useDelayRender,
  useVideoConfig,
  useCurrentFrame,
} from "remotion";

// Import the caption manifest and emoji manifest statically
import captionManifest from "../../media/downloads/7RVf25Rg0Mc/caption_manifest.json";
import emojiManifestArray from "../../media/downloads/7RVf25Rg0Mc/emoji_manifest.json";

type Word = {
  text: string;
  startMs: number;
  endMs: number;
};

type CaptionGroup = {
  startMs: number;
  endMs: number;
  words: Word[];
};

type EmojiSelection = {
  text: string;
  emoji: string;
  reason: string;
  group_id: string;
  clip_start: number;
  clip_end: number;
  start_time: number;
  end_time: number;
  matched_text: string;
};

type EmojiManifest = {
  video_id: string;
  llm_provider: string;
  llm_model: string;
  candidates: [{
    candidate_id: number;
    total_clip_duration_s: number;
    emoji_selections: EmojiSelection[];
  }];
};

const CaptionComponent: React.FC = () => {
  // All hooks must be called unconditionally at the top
  const [groups, setGroups] = useState<CaptionGroup[] | null>(null);
  const [totalDurationMs, setTotalDurationMs] = useState<number | null>(null);
  const [emojiManifest, setEmojiManifest] = useState<EmojiManifest | null>(null);
  const { delayRender, continueRender, cancelRender } = useDelayRender();
  const [handle] = useState(() => delayRender());

  // Moved the video hooks here to ensure they are called every render
  const { fps } = useVideoConfig();
  const frame = useCurrentFrame();

  useEffect(() => {
    // Process captionManifest to get candidate 1
    const candidate = captionManifest.candidates.find((c: any) => c.candidate_id === 1);
    if (!candidate) {
      throw new Error("Candidate 1 not found in caption manifest");
    }

    // Convert caption groups to our internal format
    const groupsArray: CaptionGroup[] = [];
    let maxEndTime = 0;

    candidate.caption_groups.forEach((group: any) => {
      const startMs = group.start_time * 1000;
      const endMs = group.end_time * 1000;
      const wordsArray: Word[] = [];
      group.words.forEach((word: any) => {
        const wordStartMs = word.clip_start * 1000;
        const wordEndMs = word.clip_end * 1000;
        wordsArray.push({
          text: word.word,
          startMs: wordStartMs,
          endMs: wordEndMs,
        });
        if (wordEndMs > maxEndTime) {
          maxEndTime = wordEndMs;
        }
      });
      groupsArray.push({
        startMs,
        endMs,
        words: wordsArray,
      });
      if (endMs > maxEndTime) {
        maxEndTime = endMs;
      }
    });

    setGroups(groupsArray);
    setTotalDurationMs(maxEndTime);

    // Process emoji manifest: we have an array of emoji selections for candidate 1
    // We need to wrap it in the expected format
    const emojiManifestObject: EmojiManifest = {
      video_id: "FltNsyPXNdo",
      llm_provider: "google", // We don't have this in the emoji manifest array, but we can get it from the timings? Or hardcode?
      llm_model: "gemini-3.1-flash-lite", // Similarly
      candidates: [{
        candidate_id: 1,
        total_clip_duration_s: candidate.total_clip_duration_s,
        emoji_selections: emojiManifestArray.candidates[0].emoji_selections
      }]
    };

    setEmojiManifest(emojiManifestObject);
    continueRender(handle);
  }, []); // Empty deps because we are importing statically

  // Conditional return after hooks - this is allowed
  if (!groups || totalDurationMs === null) {
    return null; // Show nothing while loading
  }

  const currentTimeMs = (frame / fps) * 1000;

  // Find the current group
  let currentGroupIndex = 0;
  if (currentTimeMs > 0) {
    // Find the first group that starts after currentTimeMs, then go back one
    const index = groups.findIndex(group => currentTimeMs < group.startMs);
    if (index === -1) {
      // currentTimeMs is beyond the last group, use the last group
      currentGroupIndex = groups.length - 1;
    } else {
      currentGroupIndex = index - 1;
    }
  }

  const currentGroup = groups[currentGroupIndex];

  // Find the active word within the current group
  let activeWordIndex = 0;
  for (let i = 0; i < currentGroup.words.length; i++) {
    const word = currentGroup.words[i];
    if (currentTimeMs >= word.startMs && currentTimeMs < word.endMs) {
      activeWordIndex = i;
      break;
    }
  }

  // Get emoji for current word based on emoji manifest and timing
  const getEmojiForCurrentTime = (): string => {
    if (!emojiManifest || !emojiManifest.candidates[0]) {
      return '';
    }

    const selections = emojiManifest.candidates[0].emoji_selections;

    // Check if current time matches any emoji selection
    for (const selection of selections) {
      const selectionStartMs = selection.clip_start * 1000;
      const selectionEndMs = selection.clip_end * 1000;

      // Check if current time is within this emoji's time range
      if (currentTimeMs >= selectionStartMs && currentTimeMs < selectionEndMs) {
        return selection.emoji;
      }
    }

    return '';
  };

  // Find the currently spoken word
  let activeWord = null;
  for (let i = 0; i < currentGroup.words.length; i++) {
    const word = currentGroup.words[i];
    if (currentTimeMs >= word.startMs && currentTimeMs < word.endMs) {
      activeWord = word;
      break;
    }
  }

  // If we found an active word, display it with emoji if applicable
  if (activeWord) {
    const emoji = getEmojiForCurrentTime();
    return (
      <AbsoluteFill style={{ justifyContent: "center", alignItems: "flex-start", paddingTop: 450 }}>
        <div style={{
          fontSize: 80,
          fontWeight: "bold",
          whiteSpace: "pre",
          color: "white",
          position: "relative",
          width: "100%",
          textAlign: "center"
        }}>
          <span
            key={`${activeWord.startMs}-active`}
            style={{
              color: "#39E508", // Active word color (green)
              transition: "color 0.2s ease"
            }}
          >
            {activeWord.text}{emoji}
          </span>
        </div>
      </AbsoluteFill>
    );
  }

  // No active word (in gap between words) - show nothing
  return null;
};

export default CaptionComponent;