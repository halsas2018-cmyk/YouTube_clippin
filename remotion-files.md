# Remotion Files in Project

## Main Project Files (in `/remotion/src/`)

### 1. `index.tsx` - **Main Remotion Composition**
- **Entry point** that registers the Remotion composition
- Uses: `Composition`, `useCurrentFrame`, `interpolate`, `getInputProps`, `staticFile`, `useDelayRender` from `remotion`
- Uses: `Video`, `Audio` from `@remotion/media`
- Imports: `CaptionOverlay` from `./CaptionOverlay`
- Defines: `calculateMetadata` (async metadata resolution), `FrameInner` (per-frame component), `VideoRoot` (composition registration)
- Registers root with `registerRoot(VideoRoot)` from `remotion`

### 2. `CaptionOverlay.tsx` - **Caption Rendering Component**
- Uses: `AbsoluteFill`, `Sequence`, `useCurrentFrame`, `useVideoConfig` from `remotion`
- Uses: `createTikTokStyleCaptions` from `@remotion/captions`
- Types: `Caption`, `TikTokPage` from `@remotion/captions`
- Defines: `CaptionPage` (renders one TikTok-style page), `CaptionOverlay` (converts manifest to captions, groups into pages, renders each in a `<Sequence>`)

### 3. `CaptionComponent.tsx` - **Legacy Caption Component** (older implementation)
- Uses: `AbsoluteFill`, `staticFile`, `useDelayRender`, `useVideoConfig`, `useCurrentFrame` from `remotion`
- Imports manifests statically: `caption_manifest.json`, `emoji_manifest.json`
- Defines: `CaptionComponent` with manual word-by-word highlighting and emoji display

### 4. `CaptionComponent.js` - **Compiled JavaScript version** of CaptionComponent.tsx

### 5. `index.js` - **Compiled JavaScript version** of index.tsx (legacy/alternative implementation)
- Similar structure to index.tsx but with hardcoded video ID and B-roll decisions
- Uses: `Composition`, `useCurrentFrame`, `interpolate` from `remotion`
- Uses: `Video`, `Audio` from `@remotion/media`
- Uses: `staticFile` from `remotion`

### 6. `metadata-node.ts` - **Metadata extraction utility**
- Uses Node.js `fs`, `path` modules (no Remotion imports)

---

## Configuration Files

### `remotion.config.ts`
- Sets public directory: `Config.setPublicDir("./public")`
- Configures default coding agent

### `package.json` (in `/remotion/`)
- Dependencies: `@remotion/cli`, `@remotion/renderer`, `remotion` (all v4.0.529)

---

## Skill Example Files (in `/.agents/skills/`) - Not Project Code

These are **example/skill files** from Remotion skills, not part of the main project:
- `.agents/skills/remotion-maps/techniques/cesium/assets/*.tsx`
- `.agents/skills/remotion-maps/techniques/maptiler/assets/*.tsx`
- `.agents/skills/remotion-best-practices/remotion-maps/...` (duplicates)
- `.agents/skills/remotion-markup/remotion-maps/...` (duplicates)

---

## Media Assets (in `/remotion/public/`)
- `section_001.mp4` - Main video section
- `mixed.m4a` - Audio file
- `asset_slot_cand_1_001.mp4` - B-roll asset 1
- `asset_slot_cand_1_002.mp4` - B-roll asset 2
- `asset_slot_cand_1_003.mp4` - B-roll asset 3
- `caption_manifest.json` - Caption timing data
- `emoji_manifest.json` - Emoji timing data
- `media/downloads/...` - Additional media assets

---

## Summary

**Active Project Files using Remotion (4 files):**
1. `/remotion/src/index.tsx` - Main composition
2. `/remotion/src/CaptionOverlay.tsx` - Caption overlay (current best-practice)
3. `/remotion/src/CaptionComponent.tsx` - Legacy caption component
4. `/remotion/src/index.js` - Legacy/alternative composition

**Configuration:**
- `/remotion/remotion.config.ts`
- `/remotion/package.json`