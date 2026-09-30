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
// CaptionPage — renders one TikTok-style page inside its own <Sequence>
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

  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
      <div
        style={{
          fontSize: 80,
          fontWeight: "bold",
          whiteSpace: "pre-wrap",
          textAlign: "center",
          color: "white",
          padding: "0 60px",
          width: "100%",
        }}
      >
        {page.tokens.map((token, tokenIndex) => {
          const isActive =
            token.fromMs <= absoluteTimeMs && token.toMs > absoluteTimeMs;
          return (
            <span
              key={`${token.fromMs}-${tokenIndex}`}
              style={{ color: isActive ? HIGHLIGHT_COLOR : "white" }}
            >
              {token.text}
            </span>
          );
        })}
        {emoji}
      </div>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// CaptionOverlay — converts the custom caption_manifest format to Caption[],
// groups into TikTok-style pages, and renders each page in a <Sequence>
// ---------------------------------------------------------------------------

export const CaptionOverlay: React.FC<{
  captionCandidate: any;
  emojiCandidate: any;
}> = ({ captionCandidate, emojiCandidate }) => {
  const { fps } = useVideoConfig();

  // Convert custom word-level format → Caption[] for @remotion/captions
  const captions: Caption[] = useMemo(() => {
    if (!captionCandidate) return [];
    const result: Caption[] = [];
    for (const group of captionCandidate.caption_groups ?? []) {
      const words = group.words ?? [];
      for (let i = 0; i < words.length; i++) {
        const word = words[i];
        const isFirst = result.length === 0;
        result.push({
          text: isFirst ? word.word : ` ${word.word}`,
          startMs: word.clip_start * 1000,
          endMs: word.clip_end * 1000,
          timestampMs: word.clip_start * 1000,
          confidence: null,
          pageBreakAfter: i === words.length - 1,
        });
      }
    }
    return result;
  }, [captionCandidate]);

  const { pages } = useMemo(
    () =>
      createTikTokStyleCaptions({
        captions,
        combineTokensWithinMilliseconds: SWITCH_CAPTIONS_EVERY_MS,
      }),
    [captions]
  );

  return (
    <AbsoluteFill>
      {pages.map((page, index) => {
        const nextPage = pages[index + 1] ?? null;
        const startFrame = (page.startMs / 1000) * fps;
        const endFrame = nextPage
          ? (nextPage.startMs / 1000) * fps
          : startFrame + (page.durationMs / 1000) * fps;
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
