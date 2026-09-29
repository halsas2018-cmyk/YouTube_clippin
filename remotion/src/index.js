import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Composition, useCurrentFrame, interpolate } from "remotion";
import { Video, Audio } from "@remotion/media";
import { staticFile } from "remotion";
import CaptionComponent from "./CaptionComponent";
// Import the source video as a static file
const section1 = staticFile("media/downloads/7RVf25Rg0Mc/sections/section_001.mp4");
// Import the audio file as a static file
const audioSrc = staticFile("media/downloads/7RVf25Rg0Mc/media/audio/mixed.wav");
// Import the B-roll assets from the broll manifest
const broll1 = staticFile("media/downloads/7RVf25Rg0Mc/media/broll/asset_slot_cand_1_001.mp4"); // AI dashboard interface
const broll2 = staticFile("media/downloads/7RVf25Rg0Mc/media/broll/asset_slot_cand_1_002.mp4"); // network nodes animation
const broll3 = staticFile("media/downloads/7RVf25Rg0Mc/media/broll/asset_slot_cand_1_003.mp4"); // diverse office team
// Import the timing data
import timings from "../../media/downloads/7RVf25Rg0Mc/final_clip_timings.json";
const FPS = 30;
const DURATION_IN_SECONDS = 16.074; // From final_clip_timings.json candidate 1 total_clip_duration_s
const DURATION_IN_FRAMES = Math.round(DURATION_IN_SECONDS * FPS);
// Find candidate 1 data
const candidate1 = timings.candidates.find(c => c.candidate_id === 1);
if (!candidate1) {
    throw new Error("Candidate 1 not found in timing data");
}
// B-roll decisions for candidate 1 (from broll_manifest.json)
// Using the asset_slots data which has the correct timing information
const brollDecisions = [
    // Asset slot 1: USE_BROLL from 0.0 to 4.662s
    {
        type: "USE_BROLL",
        start: 0.0,
        end: 4.662,
        sourceStart: 0.0, // From authoritative_timing.clip_start
        broll: broll1
    },
    // Asset slot 2: ORIGINAL_WITH_OVERLAY from 4.963 to 10.505s
    {
        type: "ORIGINAL_WITH_OVERLAY",
        start: 4.963,
        end: 10.505,
        sourceStart: 4.963, // From authoritative_timing.clip_start
        broll: broll2
    },
    // Asset slot 3: USE_BROLL from 11.807 to 15.152s
    {
        type: "USE_BROLL",
        start: 11.807,
        end: 15.152,
        sourceStart: 11.807, // From authoritative_timing.clip_start
        broll: broll3
    }
];
const TestComposition = () => {
    const frame = useCurrentFrame();
    const timeInSeconds = frame / FPS;
    return (_jsxs(_Fragment, { children: [_jsx(Audio, { src: audioSrc }), _jsx(Video, { src: section1, from: 0, style: { width: 1080, height: 1920 } }), brollDecisions.map((decision, index) => {
                if (decision.type === "ORIGINAL_WITH_OVERLAY") {
                    // For ORIGINAL_WITH_OVERLAY, we want to show both original and broll
                    // The original video is already playing as the base layer
                    // We just overlay the broll on top
                    // Check if current time is within this decision's range
                    const isInRange = timeInSeconds >= decision.start && timeInSeconds < decision.end;
                    if (!isInRange) {
                        return null; // Don't render if not in time range
                    }
                    // Calculate B-roll timing using correct Remotion principles
                    const from = Math.round(decision.start * FPS);
                    const durationInFrames = Math.round((decision.end - decision.start) * FPS);
                    const trimBefore = Math.round(decision.sourceStart * FPS);
                    // Calculate opacity for 5-frame fade-in and fade-out
                    const fadeFrames = 5;
                    const opacity = interpolate(frame, [
                        from, // Start fade-in
                        from + fadeFrames, // End fade-in
                        from + durationInFrames - fadeFrames, // Start fade-out
                        from + durationInFrames // End fade-out
                    ], [0, 1, 1, 0], {
                        extrapolateLeft: "clamp",
                        extrapolateRight: "clamp"
                    });
                    return (_jsx(Video, { src: decision.broll, trimBefore: trimBefore, durationInFrames: durationInFrames, from: from, style: {
                            width: 1080,
                            height: 1920,
                            position: "absolute",
                            top: 0,
                            left: 0,
                            opacity,
                            filter: decision.type === "ORIGINAL_WITH_OVERLAY" ? "brightness(1.05) contrast(1.05)" : "none"
                        } }, index));
                }
                else if (decision.type === "USE_BROLL") {
                    // For USE_BROLL, we want to replace the original with broll
                    // Check if current time is within this decision's range
                    const isInRange = timeInSeconds >= decision.start && timeInSeconds < decision.end;
                    if (!isInRange) {
                        return null; // Don't render if not in time range
                    }
                    // Calculate B-roll timing using correct Remotion principles
                    const from = Math.round(decision.start * FPS);
                    const durationInFrames = Math.round((decision.end - decision.start) * FPS);
                    const trimBefore = Math.round(decision.sourceStart * FPS);
                    // Calculate opacity for 5-frame fade-in and fade-out
                    const fadeFrames = 5;
                    const opacity = interpolate(frame, [
                        from, // Start fade-in
                        from + fadeFrames, // End fade-in
                        from + durationInFrames - fadeFrames, // Start fade-out
                        from + durationInFrames // End fade-out
                    ], [0, 1, 1, 0], {
                        extrapolateLeft: "clamp",
                        extrapolateRight: "clamp"
                    });
                    return (_jsx(Video, { src: decision.broll, trimBefore: trimBefore, durationInFrames: durationInFrames, from: from, style: {
                            width: 1080,
                            height: 1920,
                            position: "absolute",
                            top: 0,
                            left: 0,
                            opacity
                        } }, index));
                }
                return null; // For KEEP_ORIGINAL, we don't need an extra layer
            }), (() => {
                // We need to create jump cuts by hiding the original video at specific points
                // Based on the authoritative timings in the broll manifest, we need to cut:
                // 1. From 0.0 to 4.662s (show original)
                // 2. From 4.662 to 4.963s (jump cut - hide original for 0.301s)
                // 3. From 4.963 to 10.505s (show original)
                // 4. From 10.505 to 11.807s (jump cut - hide original for 1.302s)
                // 5. From 11.807 to 15.152s (show original)
                // 6. From 15.152 to 16.074s (jump cut - hide original for 0.922s)
                const jumpCutRanges = [
                    { start: 4.662, end: 4.963 }, // Between asset 1 and 2
                    { start: 10.505, end: 11.807 }, // Between asset 2 and 3
                    { start: 15.152, end: 16.074 } // After asset 3 to end
                ];
                return (_jsxs(_Fragment, { children: [jumpCutRanges.map((range, index) => {
                            const flashStartFrame = Math.round(range.start * FPS);
                            const flashEndFrame = Math.round(range.end * FPS);
                            const flashDuration = flashEndFrame - flashStartFrame;
                            // Create a flash effect at the jump cut
                            let opacity = 0;
                            if (frame >= flashStartFrame && frame < flashStartFrame + 5) {
                                // Fade in: 0 to 0.3 over first 5 frames
                                opacity = ((frame - flashStartFrame) / 5) * 0.3;
                            }
                            else if (frame >= flashStartFrame + 5 && frame < flashEndFrame) {
                                // Fade out: 0.3 to 0 over remaining frames
                                opacity = ((flashEndFrame - frame) / Math.max(1, flashDuration - 5)) * 0.3;
                            }
                            else if (frame >= flashEndFrame - 5 && frame < flashEndFrame) {
                                // Additional fade out at the end
                                opacity = ((frame - (flashEndFrame - 5)) / 5) * 0.3;
                            }
                            return (_jsx("div", { style: {
                                    position: "absolute",
                                    top: 0,
                                    left: 0,
                                    width: "100%",
                                    height: "100%",
                                    backgroundColor: `rgba(255, 255, 255, ${opacity})`,
                                    pointerEvents: "none"
                                } }, index));
                        }), _jsx("div", { style: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0, pointerEvents: "none", backgroundColor: "transparent" }, children: _jsx(CaptionComponent, {}) })] }));
            })()] }));
};
export const RemotionRoot = () => {
    return (_jsx(Composition, { id: "7RVf25Rg0Mc-cand1", component: TestComposition, durationInFrames: DURATION_IN_FRAMES, fps: FPS, width: 1080, height: 1920 }));
};
import { registerRoot } from "remotion";
registerRoot(RemotionRoot);
