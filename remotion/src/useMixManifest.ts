import { useState, useEffect, useCallback } from "react";
import { staticFile, useDelayRender } from "remotion";

export function useMixManifest({
  videoId,
  candidateId,
}: {
  videoId: string;
  candidateId: number;
}): string | null {
  const [audioExt, setAudioExt] = useState<string | null>(null);

  const { delayRender, continueRender, cancelRender } = useDelayRender();
  const [handle] = useState(() => delayRender("Loading mix manifest"));

  const fetchMixManifest = useCallback(async () => {
    try {
      const res = await fetch(
        staticFile(`media/downloads/${videoId}/media/audio/mix_manifest_cand${candidateId}.json`)
      );
      if (!res.ok) {
        throw new Error(`Mix manifest not found: ${res.status}`);
      }
      const data = await res.json();
      const ext = data.output_format ?? "wav";
      setAudioExt(ext);
      continueRender(handle);
    } catch (err) {
      cancelRender(err);
    }
  }, [videoId, candidateId, continueRender, cancelRender, handle]);

  useEffect(() => {
    fetchMixManifest();
  }, [fetchMixManifest]);

  return audioExt;
}