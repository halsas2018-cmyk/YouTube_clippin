/// <reference types="react" />
import React, { useMemo } from "react";
import { AbsoluteFill, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { createTikTokStyleCaptions } from "@remotion/captions";
import type { Caption, TikTokPage } from "@remotion/captions";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const HIGHLIGHT_COLOR = "#39E508";
// How many ms of captions to group onto one page
const SWITCH_CAPTIONS_EVERY_MS = 1200;

// ---------------------------------------------------------------------------
// CaptionPage — renders a single word in the center of the screen
// ---------------------------------------------------------------------------

const CaptionPage: React.FC<{
  page: TikTokPage;
  emojiCandidate: any;
}> = ({ page, emojiCandidate }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // frame is relative to the Sequence start; add page.startMs for absolute time
  const currentTimeMs = (frame / fps) * 1000;
  const absoluteTimeMs = page.startMs + currentTimeMs;

  // Resolve emoji at the current absolute clip time
  let emoji = "";
  if (emojiCandidate) {
    for (const selection of emojiCandidate.emoji_selections ?? []) {
      const startMs = selection.clip_start * 1000;
      const endMs = selection.clip_end * 1000;
      if (absoluteTimeMs >= startMs && absoluteTimeMs < endMs) {
        emoji = selection.emoji;
        break;
      }
    }
  }

  const token = page.tokens[0];
  if (!token) return null;

  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
      <div
        style={{
          fontSize: 80,
          fontWeight: "bold",
          whiteSpace: "nowrap",
          textAlign: "center",
          color: HIGHLIGHT_COLOR,
          padding: "0 40px",
        }}
      >
        {token.text.trim()}
        {emoji ? ` ${emoji}` : ""}
      </div>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// CaptionOverlay — renders one word at a time as its own sequence
// ---------------------------------------------------------------------------

export const CaptionOverlay: React.FC<{
  captionCandidate: any;
  emojiCandidate: any;
}> = ({ captionCandidate, emojiCandidate }) => {
  const { fps } = useVideoConfig();

  // Convert custom word-level format → Caption[] for @remotion/captions
  // Setting pageBreakAfter on every word ensures exactly one word per page
  const captions: Caption[] = useMemo(() => {
    if (!captionCandidate) return [];
    const result: Caption[] = [];
    for (const group of captionCandidate.caption_groups ?? []) {
      for (const word of group.words ?? []) {
        result.push({
          text: word.word,
          startMs: word.clip_start * 1000,
          endMs: word.clip_end * 1000,
          timestampMs: word.clip_start * 1000,
          confidence: null,
          pageBreakAfter: true,
        });
      }
    }
    return result;
  }, [captionCandidate]);

  const { pages } = useMemo(
    () =>
      createTikTokStyleCaptions({
        captions,
        combineTokensWithinMilliseconds: 0,
      }),
    [captions]
  );

  return (
    <AbsoluteFill>
      {pages.map((page, index) => {
        const nextPage = pages[index + 1] ?? null;
        const token = page.tokens[0];
        const nextStartMs = nextPage ? nextPage.startMs : page.startMs + page.durationMs;
        const wordEndMs = token ? token.toMs : page.startMs + page.durationMs;
        // Hold word while spoken + up to 150ms of trailing pause, or until next word starts
        const endMs = Math.min(nextStartMs, Math.max(wordEndMs, page.startMs + 100) + 150);

        const startFrame = (page.startMs / 1000) * fps;
        const endFrame = (endMs / 1000) * fps;
        const durationInFrames = Math.max(1, Math.round(endFrame - startFrame));

        if (durationInFrames <= 0) return null;

        return (
          <Sequence
            key={index}
            from={Math.round(startFrame)}
            durationInFrames={durationInFrames}
          >
            <CaptionPage page={page} emojiCandidate={emojiCandidate} />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
