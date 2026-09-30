import { staticFile } from "remotion";

export type BrollDecision = {
  type: string;
  start: number;
  end: number;
  brollSrc: string;
  trimBefore: number;
  durationInFrames: number;
  from: number;
};

export type BrollAssetSlot = {
  decision_type: string;
  authoritative_timing?: {
    clip_start?: number;
    clip_end?: number;
  };
  acquisition?: {
    local_path?: string;
  };
};

export type BrollCandidate = {
  candidate_id: number;
  asset_slots?: BrollAssetSlot[];
};

export type BuildBrollDecisionsOptions = {
  brollManifest: any;
  videoId: string;
  candidateId: number;
  fps: number;
};

export function buildBrollDecisions({
  brollManifest,
  videoId,
  candidateId,
  fps,
}: BuildBrollDecisionsOptions): BrollDecision[] {
  const brollDecisions: BrollDecision[] = [];

  const brollCandidate = brollManifest.candidates?.find(
    (c: any) => c.candidate_id === candidateId
  );
  if (!brollCandidate) return brollDecisions;

  for (const slot of brollCandidate.asset_slots ?? []) {
    if (slot.decision_type === "KEEP_ORIGINAL") continue;
    const auth = slot.authoritative_timing || {};
    const start = auth.clip_start ?? 0;
    const end = auth.clip_end ?? 0;
    if (end <= start) continue;
    if (!slot.acquisition?.local_path) continue;

    const brollSrc = `media/downloads/${videoId}/media/broll/${slot.acquisition.local_path
      .split("/")
      .pop()}`;

    brollDecisions.push({
      type: slot.decision_type,
      start,
      end,
      brollSrc: staticFile(brollSrc),
      trimBefore: 0,
      durationInFrames: Math.round((end - start) * fps),
      from: Math.round(start * fps),
    });
  }

  return brollDecisions;
}