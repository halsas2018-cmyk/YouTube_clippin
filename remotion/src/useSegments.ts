import { useState, useEffect, useRef } from "react";
import { useDelayRender } from "remotion";
import { buildSegments, type Segment, type BuildSegmentsOptions } from "./buildSegments";

export function useSegments(options: BuildSegmentsOptions): Segment[] | null {
  const [segments, setSegments] = useState<Segment[] | null>(null);

  const { delayRender, continueRender, cancelRender } = useDelayRender();
  const [handle] = useState(() => delayRender("Loading video segments"));
  const clearedRef = useRef(false);

  useEffect(() => {
    if (clearedRef.current) return;

    if (!options.selectedRanges?.length || !options.paddedRanges?.length) {
      clearedRef.current = true;
      setSegments([]);
      continueRender(handle);
      return;
    }

    buildSegments(options)
      .then((segs) => {
        if (!clearedRef.current) {
          clearedRef.current = true;
          setSegments(segs);
          continueRender(handle);
        }
      })
      .catch((err) => {
        if (!clearedRef.current) {
          clearedRef.current = true;
          cancelRender(err);
        }
      });
  }, [options, continueRender, cancelRender, handle]);

  return segments;
}