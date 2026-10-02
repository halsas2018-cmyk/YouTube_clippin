import { CalculateMetadataFunction, staticFile } from "remotion";

declare const process: any;

export type CalculateMetadataProps = {
  videoId?: string;
  candidateId?: string | number;
};

const FPS = 30;

export const calculateMetadata: CalculateMetadataFunction<CalculateMetadataProps> = async ({
  props,
}) => {
  const videoId = props.videoId ?? process.env.VIDEO_ID ?? "default";
  const candidateId = Number(props.candidateId ?? process.env.CANDIDATE_ID ?? "1");

  try {
    const res = await fetch(staticFile(`media/downloads/${videoId}/final_clip_timings.json`));
    if (!res.ok) {
      console.log("[calculateMetadata] Failed to fetch timings:", res.status);
      return { durationInFrames: FPS };
    }
    const data = await res.json();
    const candidate = data.candidates?.find((c: any) => c.candidate_id === candidateId);
    const durationSec = candidate?.total_clip_duration_s ?? null;

    if (durationSec && durationSec > 0) {
      return { durationInFrames: Math.round(durationSec * FPS) };
    }
  } catch (e) {
    console.log("[calculateMetadata] Error:", e);
  }

  return { durationInFrames: FPS };
};