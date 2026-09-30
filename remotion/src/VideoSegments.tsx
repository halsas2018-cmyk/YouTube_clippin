import { Video } from "@remotion/media";
import { staticFile } from "remotion";
import type { Segment } from "./buildSegments";

export type VideoSegmentsProps = {
  segments: Segment[];
};

export const VideoSegments: React.FC<VideoSegmentsProps> = ({ segments }) => {
  return (
    <>
      {segments.map((seg, idx) => (
        <Video
          key={idx}
          src={staticFile(seg.src)}
          trimBefore={seg.trimBefore}
          durationInFrames={seg.durationInFrames}
          from={seg.from}
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            width: 1080,
            height: 1920,
          }}
        />
      ))}
    </>
  );
};