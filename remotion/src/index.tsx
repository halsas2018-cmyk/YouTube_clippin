/// <reference types="react" />
import React, { useState, useEffect } from "react";
import { Composition, useCurrentFrame, interpolate, getInputProps } from "remotion";
import { Video, Audio } from "@remotion/media";
import { staticFile } from "remotion";

declare const process: any;

const FPS = 30;

// calculateMetadata function for the Composition
// Fetches duration from the local server (works in both Node.js and browser contexts)
// Note: The server serves the public folder at /public/ path
const calculateMetadata = async ({
  props,
}: {
  props: {
    videoId?: string;
    candidateId?: string | number;
  };
}) => {
  const videoId = props.videoId ?? process.env.VIDEO_ID ?? 'default';
  const candidateId = Number(props.candidateId ?? process.env.CANDIDATE_ID ?? '1');

  try {
    // Use the correct path - public folder is served at /public/
    const res = await fetch(`/public/media/downloads/${videoId}/final_clip_timings.json`);
    if (!res.ok) {
      console.log("[calculateMetadata] Failed to fetch timings:", res.status);
      return { durationInFrames: FPS };
    }
    const data = await res.json();
    const candidate = data.candidates?.find((c: any) => c.candidate_id === candidateId);
    const durationSec = candidate?.total_clip_duration_s ?? null;

    if (durationSec && durationSec > 0) {
      return {
        durationInFrames: Math.round(durationSec * FPS),
      };
    }
  } catch (e) {
    console.log("[calculateMetadata] Error:", e);
  }

  // Fallback to 1 second if metadata unavailable
  return {
    durationInFrames: FPS,
  };
};

const VideoRoot: React.FC = () => {
  const input = getInputProps();
  const videoId = (input.videoId as string | undefined) ?? (process.env.VIDEO_ID as string | undefined) ?? 'default';
  const candidateId = Number(
    (input.candidateId as string | undefined) ??
    (process.env.CANDIDATE_ID as string | undefined) ??
    '1'
  );

  const [timings, setTimings] = useState<any | null>(null);
  const [captionManifest, setCaptionManifest] = useState<any | null>(null);
  const [emojiManifest, setEmojiManifest] = useState<any | null>(null);
  const [brollManifest, setBrollManifest] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!videoId) {
      return;
    }

    const fetchJson = async (pathStr: string) => {
      try {
        const res = await fetch(staticFile(`media/downloads/${videoId}${pathStr}`));
        if (!res.ok) {
          throw new Error(`Failed to fetch ${pathStr}: ${res.status}`);
        }
        return await res.json();
      } catch (e) {
        console.error(e);
        throw e;
      }
    };

    const loadAll = async () => {
      try {
        const [t, c, e, b] = await Promise.all([
          fetchJson("/final_clip_timings.json"),
          fetchJson("/caption_manifest.json"),
          fetchJson("/emoji_manifest.json"),
          fetchJson("/broll_manifest.json"),
        ]);
        setTimings(t);
        setCaptionManifest(c);
        setEmojiManifest(e);
        setBrollManifest(b);
        setError(null);
      } catch (e) {
        setError(`Failed to load manifests: ${e instanceof Error ? e.message : String(e)}`);
      }
    };

    loadAll();
  }, [videoId]);

  // Find selected candidate - uses dynamic candidateId
  const candidate = timings?.candidates.find((c: any) => c.candidate_id === candidateId);

  const FrameInner: React.FC = () => {
    const frame = useCurrentFrame();
    const timeInSeconds = frame / FPS;

    if (!videoId) {
      return <div style={{ padding: 20, color: "red" }}>Error: videoId is required</div>;
    }
    if (error) {
      return <div style={{ padding: 20, color: "red" }}>Error: {error}</div>;
    }
    if (!timings || !captionManifest || !emojiManifest || !brollManifest) {
      return <div style={{ padding: 20 }}>Loading...</div>;
    }

    // Find selected candidate (default)
    if (!candidate) {
      return <div style={{ padding: 20, color: "red" }}>Candidate {candidateId} not found in timings</div>;
    }

    // Build original video segments from selected_global_ranges and padded_ranges
    const paddedRanges = candidate.padded_ranges || [];
    const selectedRanges = candidate.selected_global_ranges || [];

    const segments: {
      src: string;
      trimBefore: number;
      durationInFrames: number;
      from: number;
    }[] = [];

    let accumulatedTime = 0;
    for (const range of selectedRanges) {
      const globalStart = range.global_start;
      const globalEnd = range.global_end;
      const duration = globalEnd - globalStart;

      // Find which padded range contains this global range
      let paddedIndex = -1;
      let localStart = 0;
      for (let i = 0; i < paddedRanges.length; i++) {
        const p = paddedRanges[i];
        if (globalStart >= p.start && globalEnd <= p.end) {
          paddedIndex = i;
          localStart = globalStart - p.start;
          break;
        }
      }
      if (paddedIndex === -1) {
        console.error("No padded range found for selected global range", range);
        continue;
      }

      const sectionPath = `media/downloads/${videoId}/sections/section_${String(candidateId).padStart(3, '0')}.mp4`;
      const src = staticFile(sectionPath);

      segments.push({
        src,
        trimBefore: Math.round(localStart * FPS),
        durationInFrames: Math.round(duration * FPS),
        from: Math.round(accumulatedTime * FPS),
      });

      accumulatedTime += duration;
    }

    // Compute boundaries for jump cuts (between segments)
    const boundaries: number[] = [];
    let acc = 0;
    for (let i = 0; i < segments.length - 1; i++) {
      acc += segments[i].durationInFrames / FPS;
      boundaries.push(acc);
    }

    // Build B-roll decisions from broll_manifest asset_slots
    const brollDecisions: {
      type: string;
      start: number;
      end: number;
      sourceStart: number;
      brollSrc: string;
      trimBefore: number;
      durationInFrames: number;
      from: number;
    }[] = [];

    const brollCandidate = brollManifest.candidates?.find((c: any) => c.candidate_id === candidateId);
    if (brollCandidate) {
      const assetSlots = brollCandidate.asset_slots || [];
      for (const slot of assetSlots) {
        const decisionType = slot.decision_type;
        if (decisionType === "KEEP_ORIGINAL") {
          continue; // No extra layer needed
        }
        const auth = slot.authoritative_timing || {};
        const start = auth.clip_start ?? 0;
        const end = auth.clip_end ?? 0;
        if (end <= start) continue;

        const sectionPath = `media/downloads/${videoId}/media/broll/${slot.acquisition?.local_path?.split("/").pop() ?? ""}`;
        // If local_path is not available, we cannot load broll; skip
        if (!slot.acquisition?.local_path) continue;
        const brollSrc = sectionPath; // Store raw path, call staticFile() at point of use

        brollDecisions.push({
          type: decisionType,
          start,
          end,
          sourceStart: start, // authoritative_timing.clip_start is already clip-relative
          brollSrc,
          trimBefore: Math.round(start * FPS),
          durationInFrames: Math.round((end - start) * FPS),
          from: Math.round(start * FPS),
        });
      }
    }

    // Build caption and emoji data similar to CaptionComponent
    const captionCandidate = captionManifest.candidates?.find((c: any) => c.candidate_id === candidateId);
    const emojiCandidate = emojiManifest.candidates?.find((c: any) => c.candidate_id === candidateId);

    let groups: any[] | null = null;
    let totalDurationMs: number | null = null;
    let emojiManifestObject: any = null;

    if (captionCandidate) {
      const groupsArray: any[] = [];
      let maxEndTime = 0;
      (captionCandidate.caption_groups || []).forEach((group: any) => {
        const startMs = group.start_time * 1000;
        const endMs = group.end_time * 1000;
        const wordsArray: any[] = [];
        (group.words || []).forEach((word: any) => {
          const wordStartMs = word.clip_start * 1000;
          const wordEndMs = word.clip_end * 1000;
          wordsArray.push({
            text: word.word,
            startMs: wordStartMs,
            endMs: wordEndMs,
          });
          if (wordEndMs > maxEndTime) maxEndTime = wordEndMs;
        });
        groupsArray.push({
          startMs,
          endMs,
          words: wordsArray,
        });
        if (endMs > maxEndTime) maxEndTime = endMs;
      });
      groups = groupsArray;
      totalDurationMs = maxEndTime;
    }

    if (emojiCandidate) {
      emojiManifestObject = {
        video_id: emojiCandidate.video_id ?? videoId,
        llm_provider: emojiCandidate.llm_provider ?? "google",
        llm_model: emojiCandidate.llm_model ?? "gemini-3.1-flash-lite",
        candidates: [
          {
            candidate_id: emojiCandidate.candidate_id ?? 1,
            total_clip_duration_s: emojiCandidate.total_clip_duration_s ?? 0,
            emoji_selections: emojiCandidate.emoji_selections || [],
          },
        ],
      };
    }

    return (
      <>
        {/* Audio track - spans full composition */}
        <Audio
          src={staticFile(`media/downloads/${videoId}/media/audio/mixed_cand${candidateId}.wav`)}
        />

        {/* Original video segments */}
        {segments.map((seg, idx) => (
          <Video
            key={idx}
            src={seg.src}
            trimBefore={seg.trimBefore}
            durationInFrames={seg.durationInFrames}
            from={seg.from}
            style={{ width: 1080, height: 1920 }}
          />
        ))}

        {/* B-roll overlay layers - conditionally rendered based on time */}
        {brollDecisions.map((decision, idx) => {
          // Check if current time is within this decision's range
          const isInRange = timeInSeconds >= decision.start && timeInSeconds < decision.end;
          if (!isInRange) return null;

          const from = Math.round(decision.start * FPS);
          const durationInFrames = Math.round((decision.end - decision.start) * FPS);
          // Calculate opacity for 5-frame fade-in and fade-out
          const fadeFrames = 5;

          // Robust opacity interpolation that guarantees strictly increasing inputRange
          // for all segment durations, following Remotion best practices
          let opacity: number;
          if (durationInFrames <= fadeFrames) {
            // Too short for fade - simple linear ramp from 0 to 1
            opacity = interpolate(frame, [from, from + durationInFrames], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
          } else if (durationInFrames <= 2 * fadeFrames) {
            // Can only do symmetric partial fades: 0->1 over half, 1->0 over half
            const midPoint = from + durationInFrames / 2;
            opacity = interpolate(frame, [from, midPoint, from + durationInFrames], [0, 1, 0], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
          } else {
            // Normal case: full fade-in, hold at 1, full fade-out
            opacity = interpolate(frame, [from, from + fadeFrames, from + durationInFrames - fadeFrames, from + durationInFrames], [0, 1, 1, 0], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
          }

          return (
            <Video
              key={idx}
              src={staticFile(decision.brollSrc)}
              trimBefore={decision.trimBefore}
              durationInFrames={decision.durationInFrames}
              from={decision.from}
              style={{
                width: 1080,
                height: 1920,
                position: "absolute",
                top: 0,
                left: 0,
                opacity,
                filter: decision.type === "ORIGINAL_WITH_OVERLAY" ? "brightness(1.05) contrast(1.05)" : "none"
              }}
            />
          );
        })}

        {/* Calculate jump-cut effects for segment boundaries */}
        {boundaries.map((boundary, bIdx) => {
          const flashStartFrame = Math.round(boundary * FPS);
          const flashEndFrame = flashStartFrame + 10; // 10 frames duration
          const flashDuration = flashEndFrame - flashStartFrame;

          let opacity = 0;
          if (frame >= flashStartFrame && frame < flashStartFrame + 5) {
            // Fade in: 0 to 0.3 over first 5 frames
            opacity = ((frame - flashStartFrame) / 5) * 0.3;
          } else if (frame >= flashStartFrame + 5 && frame < flashEndFrame) {
            // Fade out: 0.3 to 0 over remaining frames
            opacity = ((flashEndFrame - frame) / Math.max(1, flashDuration - 5)) * 0.3;
          } else if (frame >= flashEndFrame - 5 && frame < flashEndFrame) {
            // Additional fade out at the end
            opacity = ((frame - (flashEndFrame - 5)) / 5) * 0.3;
          }

          return (
            <div
              key={bIdx}
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                width: "100%",
                height: "100%",
                backgroundColor: `rgba(255, 255, 255, ${opacity})`,
                pointerEvents: "none",
              }}
            />
          );
        })}

        {/* Keep caption component above video */}
        <div style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0, pointerEvents: "none", backgroundColor: "transparent" }}>
          {(() => {
            if (!groups || totalDurationMs === null) return null;
            const currentTimeMs = (frame / FPS) * 1000;

            // Find the current group
            let currentGroupIndex = 0;
            if (currentTimeMs > 0) {
              const index = groups.findIndex((g: any) => currentTimeMs < g.startMs);
              if (index === -1) {
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

            const activeWord = currentGroup.words[activeWordIndex];
            if (!activeWord) return null;

            // Get emoji for current time based on emoji manifest
            let emoji = "";
            if (emojiManifestObject && emojiManifestObject.candidates[0]) {
              const selections = emojiManifestObject.candidates[0].emoji_selections;
              for (const selection of selections) {
                const selectionStartMs = selection.clip_start * 1000;
                const selectionEndMs = selection.clip_end * 1000;
                if (currentTimeMs >= selectionStartMs && currentTimeMs < selectionEndMs) {
                  emoji = selection.emoji;
                  break;
                }
              }
            }

            return (
              <div style={{ justifyContent: "center", alignItems: "flex-start", paddingTop: 200 }}>
                <div style={{
                  fontSize: 80,
                  fontWeight: "bold",
                  whiteSpace: "pre",
                  color: "white",
                  position: "relative",
                  width: "100%",
                  textAlign: "center",
                }}>
                  <span
                    key={`${activeWord.startMs}-active`}
                    style={{
                      color: "#39E508",
                      transition: "color 0.2s ease",
                    }}
                  >
                    {activeWord.text}{emoji}
                  </span>
                </div>
              </div>
            );
          })()}
        </div>
      </>
    );
  };

  return (
    <Composition
      id={`${videoId}-cand${candidateId}`}
      component={FrameInner}
      calculateMetadata={calculateMetadata}
      fps={FPS}
      width={1080}
      height={1920}
    />
  );
};

export default VideoRoot;

import { registerRoot } from "remotion";
registerRoot(VideoRoot);