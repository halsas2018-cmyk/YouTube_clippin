// This module runs in Node.js context during calculateMetadata
// It can use Node.js APIs like fs and path

import * as fs from "fs";
import * as path from "path";

export interface TimingsData {
  candidates: Array<{
    candidate_id: number;
    total_clip_duration_s: number;
    selected_global_ranges: Array<{ global_start: number; global_end: number }>;
    padded_ranges: Array<{ start: number; end: number }>;
  }>;
}

export function fetchCandidateDuration(videoId: string, candidateId: number): number | null {
  try {
    const projectRoot = path.resolve(__dirname, "..", "..", "..");
    const filePath = path.join(projectRoot, "media", "downloads", videoId, "final_clip_timings.json");
    console.log("[metadata-node.ts] fetchCandidateDuration called with:", videoId, candidateId);
    console.log("[metadata-node.ts] Looking for file at:", filePath);
    console.log("[metadata-node.ts] File exists:", fs.existsSync(filePath));
    if (!fs.existsSync(filePath)) {
      return null;
    }
    const fileContent = fs.readFileSync(filePath, "utf-8");
    const data: TimingsData = JSON.parse(fileContent);
    const candidate = data.candidates.find((c) => c.candidate_id === candidateId);
    const duration = candidate?.total_clip_duration_s ?? null;
    console.log("[metadata-node.ts] Found duration:", duration);
    return duration;
  } catch (e) {
    console.log("[metadata-node.ts] Error:", e);
    return null;
  }
}