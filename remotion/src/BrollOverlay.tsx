import { Video } from "@remotion/media";
import { Img, interpolate, staticFile } from "remotion";
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

        const isOverlay = decision.type === "ORIGINAL_WITH_OVERLAY";
        const finalOpacity = isOverlay ? opacity * 0.4 : opacity;
        const isImage = /\.(jpe?g|png|webp)$/i.test(decision.brollSrc);

        const sharedStyle = {
          width: 1080,
          height: 1920,
          position: "absolute" as const,
          top: 0,
          left: 0,
          objectFit: "cover" as const,
          opacity: finalOpacity,
          filter: isOverlay
            ? "brightness(1.05) contrast(1.05)"
            : "none",
        };

        if (isImage) {
          return (
            <Img
              key={idx}
              src={staticFile(decision.brollSrc)}
              durationInFrames={decision.durationInFrames}
              from={decision.from}
              style={sharedStyle}
            />
          );
        }

        return (
          <Video
            key={idx}
            src={staticFile(decision.brollSrc)}
            volume={0}
            trimBefore={decision.trimBefore}
            durationInFrames={decision.durationInFrames}
            from={decision.from}
            style={sharedStyle}
          />
        );
      })}
    </>
  );
};