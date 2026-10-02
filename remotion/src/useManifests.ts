import { useState, useEffect, useCallback } from "react";
import { staticFile, useDelayRender } from "remotion";

export type Manifests = {
  timings: any;
  captionManifest: any;
  emojiManifest: any;
  brollManifest: any;
};

export type UseManifestsOptions = {
  videoId: string;
};

export function useManifests({ videoId }: UseManifestsOptions): Manifests | null {
  const [timings, setTimings] = useState<any | null>(null);
  const [captionManifest, setCaptionManifest] = useState<any | null>(null);
  const [emojiManifest, setEmojiManifest] = useState<any | null>(null);
  const [brollManifest, setBrollManifest] = useState<any | null>(null);

  const { delayRender, continueRender, cancelRender } = useDelayRender();
  const [handle] = useState(() => delayRender("Loading manifests"));

  const fetchJson = useCallback(
    async (pathStr: string) => {
      const res = await fetch(staticFile(`media/downloads/${videoId}${pathStr}`));
      if (!res.ok) {
        throw new Error(`Failed to fetch ${pathStr}: ${res.status}`);
      }
      return res.json();
    },
    [videoId]
  );

  const loadAll = useCallback(async () => {
    try {
      const [t, c, e, b] = await Promise.all([
        fetchJson("/final_clip_timings.json"),
        fetchJson("/caption_manifest.json"),
        fetchJson("/emoji_manifest.json"),
        fetchJson("/broll_manifest.json"),
      ]);
      setTimings(t);
      setCaptionManifest(c);
      setEmojiManifest(e);
      setBrollManifest(b);
      continueRender(handle);
    } catch (err) {
      cancelRender(err);
    }
  }, [fetchJson, continueRender, cancelRender, handle]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  if (!timings || !captionManifest || !emojiManifest || !brollManifest) {
    return null;
  }

  return { timings, captionManifest, emojiManifest, brollManifest };
}