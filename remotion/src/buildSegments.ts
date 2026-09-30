export type Segment = {
  src: string;
  trimBefore: number;
  durationInFrames: number;
  from: number;
};

export type BuildSegmentsOptions = {
  selectedRanges: { global_start: number; global_end: number }[];
  paddedRanges: { start: number; end: number }[];
  videoId: string;
  candidateId: number;
  fps: number;
};

export function buildSegments({
  selectedRanges,
  paddedRanges,
  videoId,
  candidateId,
  fps,
}: BuildSegmentsOptions): Segment[] {
  const segments: Segment[] = [];
  let accumulatedTime = 0;

  for (const range of selectedRanges) {
    const globalStart = range.global_start;
    const globalEnd = range.global_end;
    const duration = globalEnd - globalStart;

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

    const sectionPath = `media/downloads/${videoId}/sections/section_${String(
      candidateId
    ).padStart(3, "0")}.mp4`;

    segments.push({
      src: sectionPath,
      trimBefore: Math.round(localStart * fps),
      durationInFrames: Math.round(duration * fps),
      from: Math.round(accumulatedTime * fps),
    });

    accumulatedTime += duration;
  }

  return segments;
}