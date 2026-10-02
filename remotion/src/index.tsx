import React from "react";
import {
  Composition,
  useCurrentFrame,
  getInputProps,
  staticFile,
} from "remotion";

declare const process: any;

import { Audio } from "@remotion/media";
import { calculateMetadata } from "./calculateMetadata";
import { useManifests } from "./useManifests";
import { useMixManifest } from "./useMixManifest";
import { useSegments } from "./useSegments";
import { buildBrollDecisions, type BrollDecision } from "./buildBrollDecisions";
import { BrollOverlay } from "./BrollOverlay";
import { CaptionLayer } from "./CaptionLayer";
import { VideoSegments } from "./VideoSegments";
import { JumpCutFlashes } from "./JumpCutFlashes";

const FPS = 30;

// ---------------------------------------------------------------------------
// FrameInner — the actual per-frame composition component
// ---------------------------------------------------------------------------

const FrameInner: React.FC = () => {
  const input = getInputProps();
  const videoId =
    (input.videoId as string | undefined) ??
    (process.env.VIDEO_ID as string | undefined) ??
    "default";
  const candidateId = Number(
    (input.candidateId as string | undefined) ??
      (process.env.CANDIDATE_ID as string | undefined) ??
      "1"
  );

  const frame = useCurrentFrame();
  const timeInSeconds = frame / FPS;

  // --- Load all manifests via hooks (all called unconditionally) ---
  const manifests = useManifests({ videoId });
  const audioExt = useMixManifest({ videoId, candidateId });

  if (!manifests) return null;

  const { timings, captionManifest, emojiManifest, brollManifest } = manifests;

  // --- Candidate lookup ---
  const candidate = timings.candidates?.find(
    (c: any) => c.candidate_id === candidateId
  );
  if (!candidate) return null;

  // --- Build video segments from selected_global_ranges (async via hook) ---
  const segments = useSegments({
    selectedRanges: candidate.selected_global_ranges || [],
    paddedRanges: candidate.padded_ranges || [],
    videoId,
    candidateId,
    fps: FPS,
  });
  if (!segments) return null;

  // --- Jump-cut flash boundaries ---
  const boundaries: number[] = [];
  let acc = 0;
  for (let i = 0; i < segments.length - 1; i++) {
    acc += segments[i].durationInFrames / FPS;
    boundaries.push(acc);
  }

  // --- Build B-roll decisions ---
  const brollDecisions = buildBrollDecisions({
    brollManifest,
    videoId,
    candidateId,
    fps: FPS,
  });

  // --- Caption and emoji candidates ---
  const captionCandidate = captionManifest.candidates?.find(
    (c: any) => c.candidate_id === candidateId
  );
  const emojiCandidate = emojiManifest.candidates?.find(
    (c: any) => c.candidate_id === candidateId
  );

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------
  return (
    <>
      {/* Audio track — mixed_cand{N}.{mp3|wav} (format determined by mix manifest) */}
      <Audio
        src={staticFile(
          `media/downloads/${videoId}/media/audio/mixed_cand${candidateId}.${audioExt}`
        )}
      />

      {/* Original video segments */}
      <VideoSegments segments={segments} />

      {/* B-roll overlay layers */}
      <BrollOverlay
        brollDecisions={brollDecisions}
        frame={frame}
        fps={FPS}
      />

      {/* Jump-cut flash effects */}
      <JumpCutFlashes boundaries={boundaries} frame={frame} fps={FPS} />

      {/* Captions — best-practice AbsoluteFill + Sequence implementation */}
      <CaptionLayer
        captionCandidate={captionCandidate}
        emojiCandidate={emojiCandidate ?? null}
      />
    </>
  );
};

// ---------------------------------------------------------------------------
// VideoRoot — registers compositions
// ---------------------------------------------------------------------------

const VideoRoot: React.FC = () => {
  const input = getInputProps();
  const videoId =
    (input.videoId as string | undefined) ??
    (process.env.VIDEO_ID as string | undefined) ??
    "default";
  const candidateId = Number(
    (input.candidateId as string | undefined) ??
      (process.env.CANDIDATE_ID as string | undefined) ??
      "1"
  );

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