import { staticFile } from "remotion";

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

export async function buildSegments({
  selectedRanges,
  paddedRanges,
  videoId,
  candidateId,
  fps,
}: BuildSegmentsOptions): Promise<Segment[]> {
  // Fetch sections manifest to get actual file extensions
  const manifestRes = await fetch(
    staticFile(`media/downloads/${videoId}/sections/sections_metadata.json`)
  );
  if (!manifestRes.ok) {
    throw new Error(`Failed to load sections manifest: ${manifestRes.status}`);
  }
  const manifest = await manifestRes.json();

  // Build a map of section_id -> file_name
  const sectionFiles = new Map<string, string>();
  for (const section of manifest.sections) {
    sectionFiles.set(section.section_id, section.file_name);
  }

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

    const sectionId = `section_${String(paddedIndex + 1).padStart(3, "0")}`;
    const fileName = sectionFiles.get(sectionId) ?? `${sectionId}.mp4`;
    const sectionPath = `media/downloads/${videoId}/sections/${fileName}`;

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