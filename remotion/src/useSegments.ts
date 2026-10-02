import { useState, useEffect, useCallback } from "react";
import { staticFile, useDelayRender } from "remotion";
import { buildSegments, type Segment, type BuildSegmentsOptions } from "./buildSegments";

export function useSegments(options: BuildSegmentsOptions): Segment[] | null {
  const [segments, setSegments] = useState<Segment[] | null>(null);
  const [loading, setLoading] = useState(true);

  const { delayRender, continueRender, cancelRender } = useDelayRender();
  const [handle] = useState(() => delayRender());

  const loadSegments = useCallback(async () => {
    // Skip if no ranges to process yet
    if (!options.selectedRanges.length || !options.paddedRanges.length) {
      setLoading(false);
      continueRender(handle);
      return;
    }
    try {
      const segs = await buildSegments(options);
      setSegments(segs);
      setLoading(false);
      continueRender(handle);
    } catch (err) {
      cancelRender(err);
    }
  }, [options, continueRender, cancelRender, handle]);

  useEffect(() => {
    loadSegments();
  }, [loadSegments]);

  // Return null while loading or no data, array when ready
  return segments;
}