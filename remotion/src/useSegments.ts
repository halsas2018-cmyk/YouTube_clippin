import { useState, useEffect, useCallback } from "react";
import { staticFile, useDelayRender } from "remotion";
import { buildSegments, type Segment, type BuildSegmentsOptions } from "./buildSegments";

export function useSegments(options: BuildSegmentsOptions): Segment[] | null {
  const [segments, setSegments] = useState<Segment[] | null>(null);

  const { delayRender, continueRender, cancelRender } = useDelayRender();
  const [handle] = useState(() => delayRender());

  const loadSegments = useCallback(async () => {
    // Skip if no ranges to process yet - DON'T continueRender, wait for real data
    if (!options.selectedRanges.length || !options.paddedRanges.length) {
      return;
    }
    try {
      const segs = await buildSegments(options);
      setSegments(segs);
      continueRender(handle);
    } catch (err) {
      cancelRender(err);
    }
  }, [options, continueRender, cancelRender, handle]);

  useEffect(() => {
    loadSegments();
  }, [loadSegments]);

  return segments;
}