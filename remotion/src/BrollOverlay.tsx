import { Video } from "@remotion/media";
import { interpolate, staticFile } from "remotion";
import type { BrollDecision } from "./buildBrollDecisions";

export type BrollOverlayProps = {
  brollDecisions: BrollDecision[];
  frame: number;
  fps: number;
};

const FADE_FRAMES = 5;

export const BrollOverlay: React.FC<BrollOverlayProps> = ({
  brollDecisions,
  frame,
  fps,
}) => {
  const timeInSeconds = frame / fps;

  return (
    <>
      {brollDecisions.map((decision, idx) => {
        const isInRange =
          timeInSeconds >= decision.start && timeInSeconds < decision.end;
        if (!isInRange) return null;

        const from = Math.round(decision.start * fps);
        const durationInFrames = Math.round(
          (decision.end - decision.start) * fps
        );

        let opacity: number;
        if (durationInFrames <= FADE_FRAMES) {
          opacity = interpolate(
            frame,
            [from, from + durationInFrames],
            [0, 1],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
          );
        } else if (durationInFrames <= 2 * FADE_FRAMES) {
          const midPoint = from + durationInFrames / 2;
          opacity = interpolate(
            frame,
            [from, midPoint, from + durationInFrames],
            [0, 1, 0],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
          );
        } else {
          opacity = interpolate(
            frame,
            [
              from,
              from + FADE_FRAMES,
              from + durationInFrames - FADE_FRAMES,
              from + durationInFrames,
            ],
            [0, 1, 1, 0],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
          );
        }

        return (
          <Video
            key={idx}
            src={staticFile(decision.brollSrc)}
            trimBefore={decision.trimBefore}
            durationInFrames={decision.durationInFrames}
            from={decision.from}
            style={{
              width: 1080,
              height: 1920,
              position: "absolute",
              top: 0,
              left: 0,
              opacity,
              filter:
                decision.type === "ORIGINAL_WITH_OVERLAY"
                  ? "brightness(1.05) contrast(1.05)"
                  : "none",
            }}
          />
        );
      })}
    </>
  );
};