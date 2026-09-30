import { Solid, interpolate, useVideoConfig } from "remotion";

export type JumpCutFlashesProps = {
  boundaries: number[];
  frame: number;
  fps: number;
};

const FLASH_DURATION_FRAMES = 10;
const FADE_IN_FRAMES = 5;
const MAX_OPACITY = 0.3;

export const JumpCutFlashes: React.FC<JumpCutFlashesProps> = ({
  boundaries,
  frame,
  fps,
}) => {
  const { width, height } = useVideoConfig();

  return (
    <>
      {boundaries.map((boundary, bIdx) => {
        const flashStartFrame = Math.round(boundary * fps);
        const flashEndFrame = flashStartFrame + FLASH_DURATION_FRAMES;

        if (frame < flashStartFrame || frame >= flashEndFrame) {
          return null;
        }

        const progress = (frame - flashStartFrame) / FLASH_DURATION_FRAMES;

        // Fade in for first half, fade out for second half
        let opacity = 0;
        if (progress < 0.5) {
          opacity = interpolate(progress, [0, 0.5], [0, MAX_OPACITY]);
        } else {
          opacity = interpolate(progress, [0.5, 1], [MAX_OPACITY, 0]);
        }

        return (
          <Solid
            key={bIdx}
            width={width}
            height={height}
            color="#FFFFFF"
            style={{
              position: "absolute",
              top: 0,
              left: 0,
              pointerEvents: "none",
              opacity,
            }}
          />
        );
      })}
    </>
  );
};