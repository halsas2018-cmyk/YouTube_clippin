import { CaptionOverlay } from "./CaptionOverlay";

export type CaptionLayerProps = {
  captionCandidate: any;
  emojiCandidate: any | null;
};

export const CaptionLayer: React.FC<CaptionLayerProps> = ({
  captionCandidate,
  emojiCandidate,
}) => {
  if (!captionCandidate) return null;

  return (
    <CaptionOverlay
      captionCandidate={captionCandidate}
      emojiCandidate={emojiCandidate}
    />
  );
};