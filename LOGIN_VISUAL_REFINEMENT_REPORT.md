# EKIP Login Visual Refinement — Handoff Report

**Date:** 2026-10-16  
**Branch:** `feature/organisation-knowledge-management`  
**Task:** Login animation speed, image scale, quality, and responsive presentation.  
**Decision:** The automated, measured and browser-observed checks PASS for the final refinement below: a re-encoded, interpolated 100 s GIF and a subtle tonal frame. **Visual acceptance is NOT VERIFIED and awaits your review in the real login page.** Live credential-based Playwright login tests were skipped because no synthetic login credentials were configured.

## Final pacing — 100 s loop — 2026-10-16 (supersedes the 144 s and 180 s timings below)

At your request the loop was set to **100.00 s, about 16.7 s per scene**, keeping the 3:1 hold-to-dissolve balance: a 12.5 s push-in (20 frames at 62/63 cs) and a 4.17 s dissolve (40 frames at 10/11 cs). Scenes alternate between 1,666 and 1,667 cs so the loop totals exactly 10,000 cs.
- Delays only: 0 non-delay bytes changed, the size is still 18,091,626 bytes, and the original backup is untouched.
- The smoke spec was updated to 10,000 cs, 62/63 cs push-in delays and 10/11 cs dissolve delays. It passed 2 tests with 1 skipped (live login: no credentials).
- Chromium on `http://127.0.0.1:5173/`, sampled for the first 20 s: push-in frames changed every 0.60–0.66 s, the first dissolve ran from 11.9 s to 17.4 s, and the largest change between samples was 2.89 (smooth).

## Pacing adjustment — 2026-10-16 (historical)

The 180 s loop felt too slow in review. It was retimed to **24 s per scene: an 18 s push-in at 90 cs × 20 frames, then a 6 s dissolve at 15 cs × 40 frames. The loop is 144.00 s** (delays: 120 × 90 cs, 240 × 15 cs).
- Delays only: 0 non-delay bytes changed, the size is still 18,091,626 bytes, and the original backup is untouched.
- The smoke spec was updated to 14,400 cs, 90 cs push-in delays and 15 cs dissolve delays. It passed 2 tests with 1 skipped (live login: no credentials).
- Chromium on `http://127.0.0.1:5173/`, sampled for 30 s: push-in frames changed every 0.87–0.93 s, the first dissolve ran from 17.5 s to 24.7 s, and the largest change between samples was 2.89 (smooth).

## Addendum — size comparison and 180 s pacing (historical) — 2026-10-16 (timing supersedes the 100 s figures below)

**Size optimisation, compared and rejected.** A 9.59 MB version was regenerated with the same encoder, frames, delays, seam handling and tolerances, differing only in using dithered pixel flips for the dissolves.

Compared with the 18.09 MB file at 2× Retina display scale, against ideal blends of the original frames:

| Dissolve point | 18.09 MB | 9.59 MB |
|---|---|---|
| 15% | 35.5 dB | 34.4 dB |
| 35% | 35.0 dB | 33.5 dB |
| 50% | 35.1 dB | 34.5 dB |
| 65% | 34.9 dB | 33.1 dB |
| 85% | 38.5 dB | 30.0 dB |

- **Visual inspection** of side-by-side Retina crops at 35% and 50% showed a visible regular dot grid in the 9.59 MB dissolves, on dark face and shelf areas and across the bright window. The 18.09 MB file shows only the normal fine dither. Neither shows banding beyond the shared palette.
- **Discarded metric:** an automated "grid-period energy" measure was discarded as unreliable, because it targeted the wrong frequency.
- **Decision:** keep 18.09 MB. Smaller GIFs in this family come only from flip patterns (grid) or looser tolerances (stale pixels in held scenes; measured 35.3 dB arrival at 15.6 MB). The remaining lossless lever, LZW re-optimisation with a tool such as gifsicle, is not installed and typically saves little. A video format would be far smaller but was ruled out to keep GIF.

**Final pacing (delays only).** The 100 s loop still felt fast in review. Each scene was on screen for only about 11.7 s, and the push-in now drifts continuously instead of resting on still frames. The same 360 frames were retimed: 0 bytes changed outside the 360 delay fields, and the size is still 18,091,626 bytes.

| Property | 100 s version | **Final** |
|---|---|---|
| Delays | 80 × 58, 40 × 59, 120 × 12, 120 × 13 cs | **120 × 115 cs (push-in), 120 × 17, 120 × 18 cs (dissolve)** |
| Loop | 100.00 s | **180.00 s** (`ffprobe` 180.000000) |
| Per scene | 11.7 s push-in + 5.0 s dissolve | **23.0 s push-in + 7.0 s dissolve = 30.0 s** |
| SHA-256 | `1720e2dd…a9` | `bd72ef4d97b28bfe1c8439b2f825e84e7180c21359050da45af52139b91822e1` |

Per-frame steps are unchanged (0.1% zoom, 2.5% opacity), so smoothness is preserved at the slower pace.

**Browser playback.** Chromium on the running local dev server `http://127.0.0.1:5173/` was sampled every 55 ms for 38 s.
- Push-in frames changed every 1.13–1.17 s.
- The first dissolve ran from 22.6 s to 30.7 s.
- The largest change between samples was 2.89.
- A full 180 s loop was not watched; the change was delays only, and the metadata confirms 180.00 s.

**Checks.** The smoke spec was updated to 18,000 cs total, 115 cs push-in delays and dissolve delays of 17/18 cs summing to 700 per scene. It passed 2 tests with 1 skipped (live login: no credentials). The design, CSS and the original backup were not changed.

## Final refinement: interpolated 100 s animation and subtle tonal frame — 2026-10-16 (supersedes both sections below)

Re-encoding and adding in-between frames were explicitly approved for this step.

### Animation: what was built

**Source.** The untouched `ekip-login-research-rotation-original.gif`: 60 frames, 6 scenes × 10. Frames 0–5 of each scene are a 2.0% push-in; frames 6–9 are exact linear 20/40/60/80% cross-fades into the next scene. The six-scene order, composition, 400×500 size and 4:5 ratio are unchanged.

**Interpolation.** In-between frames are linear blends of consecutive original frames, so the original 60 frames remain anchor points.
- **Push-in:** each of the 5 push-in steps (0.4% zoom, under 1 px) becomes 4 frames, 0.1% zoom each, for 20 frames over about 11.7 s per scene.
- **Dissolve:** each of the 5 dissolve steps (20%) becomes 8 frames, 2.5% opacity each, for 40 frames over 5.0 s per scene.
- **Timing:** delays are cumulatively rounded so the loop is exactly 10,000 cs.

**Encoding** (custom Python/NumPy/Pillow encoder; the scripts live in the session scratchpad and are not added to the repository):
- **Palette and dither:** one shared 255-colour palette (ffmpeg `palettegen stats_mode=full` over all frames) with a fixed 8×8 ordered dither. Unchanged regions keep identical pixel values from frame to frame.
- **Inter-frame transparency** (disposal 1): each frame stores only pixels whose colour differs from what is on screen by more than a tolerance. The tolerance is 6 levels during push-in and 12 during dissolves, where motion hides the lag. Across each dissolve's final 20% step it tightens gradually from 12 to 3, and each scene's arrival frame refreshes at 3, so held scenes settle clean without a visible snap.
- **Seamless loop:** frame 0 is the refreshed end-of-loop state (two-pass), so the loop seam is as gentle as any other scene arrival.

**Alternatives measured and rejected:**

| Option | Size | Why rejected |
|---|---|---|
| Standard ffmpeg encodes | 36.6–50.7 MB | Far too large |
| Dithered pixel-flip interpolation | 10.1 MB | Faint regular grid texture during dissolves at Retina scale |
| Pixel-flip with 10% anchors | 14.1 MB | Grid still visible |
| True blend, uniform tolerance 8 | 19.5 MB | Larger, and less clean when scenes settle |
| True blend, uniform tolerance 12 | 15.6 MB | Stale pixels in held scenes (arrival PSNR 35.3 dB) |

The chosen hybrid has the best measured quality of the true-blend family at a mid-range size.

| Property | Before (delays-only, 94.2 s) | After |
|---|---|---|
| Frames | 60 | **360** (60 per scene: 20 push-in + 40 dissolve) |
| Delay distribution | 6 × 400, 30 × 170, 24 × 80 cs | **80 × 58 cs, 40 × 59 cs (push-in); 120 × 12 cs, 120 × 13 cs (dissolve)** |
| Loop duration (metadata / ffprobe) | 94.20 s | **100.00 s** / 100.000000 |
| Per scene | 15.7 s | 16.67 s: about 11.7 s slow push-in, then a 5.0 s dissolve |
| Largest frame-to-frame change (mean abs, 0–255) | about 23 (20% step) | **3.7** (arrivals and loop seam 2.3–2.9) |
| Dimensions / loop | 400×500 / infinite | 400×500 / infinite (NETSCAPE2.0, loop 0) |
| Palette / disposal | 64-colour global + per-frame local / 2 | 255-colour global / 1 |
| File size | 5,280,679 bytes | **18,091,626 bytes (18.09 MB)** |
| SHA-256 | `ad72c376…8e` | `1720e2dddb1174bc02fd9b7e01ef614686032487add9045afde5ce389a78a2a9` |

**Quality evidence:**
- **Decoding:** Pillow decodes all 360 frames, and sampled frames match the encoder's intended composites exactly (max difference 0). `ffmpeg -i … -f null -` exits 0; its `non monotonically increasing dts` lines are null-output timestamp warnings from the 12–13 cs delays, not decode errors.
- **Display-scale PSNR** (bilinear upscale to 2× Retina size) against ideal float blends of the original frames: 43.9 dB on scene arrivals, about 36 dB during the push-in, 30.2 dB at a mid-dissolve frame and 35.4 dB at a dissolve anchor.
- **Size:** the file is 3.4× the original 5.3 MB. That was accepted to prioritise smooth motion as requested; the 10.1 MB flip variant remains an option if load size matters more than the faint dissolve texture.

### Border and background

**Inspected first:**
- The GIF has no built-in border. Its edges are warm dark brown: mean `#5c493d`, per-scene range `#2e211a`–`#a79178`.
- The page panel renders as `#1c2b2e` right around the artwork and `#1f2f31` above it (sampled from Chromium screenshots); the page background is `#101b21`.

**CSS** (`frontend/src/styles.css`, login visual rules only; the previous feather mask was removed):
- `.login-visual-card` is a transparent wrapper sized to the framed artwork: `--login-visual-frame: 6px; width: min(100%, calc(min(47.2vh, 496px) + 2 * var(--login-visual-frame) + 2px))`. The artwork stays the same size as before.
- `.login-visual-picture` is the thin tonal mat:
  - padding `6px`;
  - a warm hairline border `1px solid #d8c4a51c`;
  - radius 14px;
  - `linear-gradient(160deg, #313533, #2a3030)`, about 75% panel colour warmed 25% toward the artwork edge colour;
  - a soft, low-opacity shadow `0 18px 44px #050e0c3d`.
- `.login-visual-picture img` has an exact 4:5 `aspect-ratio`, `object-fit: contain` and radius 9px.
- The caption stays outside the frame with light text, and the warm glow on `.login-visual` is kept. There is no pale card and no empty pale area under the image.

### Browser verification actually performed

Isolated Vite dev server on `127.0.0.1:4319` (API proxy target is the isolated `127.0.0.1:8001`), headless Chromium.
- **Layout:**

  | Viewport | Frame | Image | Image ratio | Frame inset | Panel gutters |
  |---|---|---|---|---|---|
  | 1440×900 @1x and @2x | 439×545 | 424.8×531 | 0.8000 | 7 px every side | 141 / 141 px |
  | 1920×1080 | — | 496×620 | — | 7 px | 225 / 225 px |
  | 1280×720 | — | 339.8×424.8 | — | 7 px | 143 / 143 px |
  | 1024×768 | — | 362.5×453.1 | — | 7 px | 68 / 68 px |

  At 820×1180 and 390×844 @2x the artwork is hidden as before and the form is visible. There was no horizontal overflow anywhere.
- **Screenshots reviewed by eye:** 1440×900 @1x, 2× Retina edge crops and 390×844 @2x. The mat (`#2f3432` rendered) sits a gentle step above the panel (`#1a282b` rendered) with a faint warm hairline. No white rectangle, no harsh shadow, no excess space.
- **Full-loop playback:** the rendered image was captured about every 56 ms for 110 s (1,958 samples; `currentSrc` = the GIF, reduced motion off).
  - The first sample was matched exactly (difference 0.00) at **t = 99.93 s**.
  - The largest change between samples was 3.12, with no jumps.
  - Six dissolves were observed, starting 16.50–16.77 s apart and each about 6.2 s by a 1-second-change measure (5 s blend plus settle).
  - Median 1-second change was 1.6 during holds and 12.6 during dissolves.
  - A 13-frame strip of the 10.6–17.8 s transition, at 0.6 s steps, was reviewed by eye. The fade is gradual, without stages or texture, and the arrival settles cleanly.

### Files changed in this refinement

- `frontend/public/images/ekip-login-research-rotation.gif`: re-encoded with interpolated frames (the original backup is untouched, SHA-256 `670ceecc…849b`).
- `frontend/src/styles.css`: `.login-visual-card`, `.login-visual-picture` and `.login-visual-picture img` only.
- `frontend/e2e/smoke.spec.ts`:
  - timing: 360 frames, total 10,000 cs, and per scene 20 push-in delays of 58/59 cs plus 40 dissolve delays of 12/13 cs summing to 500;
  - layout: no pale card, mat padding 4–10 px, 1 px border, dark gradient (max channel < 80), equal insets, no mask, symmetric gutters, 4:5 image, light caption.
- this report

### Verification run

| Command | Result |
|---|---|
| `npx vitest run src/App.test.tsx` (from `frontend/`) | PASS: 1 file, 13 tests |
| `EKIP_API_PROXY_TARGET=http://127.0.0.1:8001 npx playwright test e2e/smoke.spec.ts` (from `frontend/`) | 2 passed, 1 skipped (live login: no synthetic credentials), 0 failed |
| `npm run check` (from `frontend/`) | PASS, exit 0 |
| `git diff --check -- frontend/src/styles.css` | PASS, exit 0 |
| `git diff --no-index --check /dev/null frontend/e2e/smoke.spec.ts` | 0 whitespace issues |

Checks not run, and why:
- Full Vitest suite, production build and full E2E suite: not run, because the scope is the login asset, login CSS and smoke test.
- Safari/Firefox playback: not checked; GIF disposal-1 transparency is standard, but it was verified only in Chromium, Pillow and ffmpeg.
- Real-network load time of the 18 MB asset: not measured.
- Credential-based login E2E: skipped by its guard.

No production API (port 8000), `data/` content or secrets were touched. The temporary dev server was stopped and ports 4319 and 4173 were confirmed closed.

## Cinematic timing and frameless blend — 2026-10-16 (historical; superseded by the final refinement above)

### Why 53.4 s still felt fast

The GIF is six scenes of 10 frames. Measurements on the 53.4 s file:
- **Push-in:** the camera zooms by 2.0% over frames 0→5 (best centre-zoom fit, residual ≈ 3.1–3.6). That is about 0.4% per step, under 1 px of edge movement at the displayed size.
- **Dissolves:** frames 6–9 are exact linear cross-fades at 20%, 40%, 59% and 78–79% (least-squares blend fit; residual 2.2–10.7). Each scene change is five equal 20% opacity steps ending on the next scene's frame 0.
- **Time on screen:** each scene was fully visible for only 6.5 s of its 8.9 s, and every scene change arrived at a steady 8.9 s rhythm.

Because the push-in steps are sub-pixel, holds can be long without visible twitching. Most of the extra time therefore goes into the holds, and the dissolve steps are slowed more modestly.

### Animation change (delays only)

The new per-scene pattern, repeated for all six scenes, is `[400, 170, 170, 170, 170, 170, 80, 80, 80, 80]` cs:
- a 4.0 s calm hold on each scene's clean arrival frame;
- 1.7 s per push-in frame, so the 2% push-in now spans 12.5 s instead of 6.5 s;
- 0.8 s per dissolve frame. Equal steps preserve the artwork's linear fade, which is now about 3.2 s instead of 2.4 s.

| Property | Before (53.4 s) | After |
|---|---|---|
| Frames | 60 | 60 (same order) |
| Delay distribution | 6 × 150, 30 × 100, 24 × 60 cs | **6 × 400, 30 × 170, 24 × 80 cs** |
| Loop duration (frame metadata) | 53.40 s | **94.20 s** (`ffprobe` 94.200000) |
| Per scene | 8.9 s (6.5 s fully visible) | 15.7 s (12.5 s fully visible) |
| Dimensions / loop / disposal | 400×500 / infinite / 2 | Unchanged |
| File size | 5,280,679 bytes | 5,280,679 bytes |
| SHA-256 | `8b1821fd…c7b` | `ad72c3769468be4eac9b784adc36c293a68f862af420edf184b74f51b74fae8e` |

0 bytes differ outside the 60 two-byte delay fields, compared with both the 53.4 s file and the untouched `ekip-login-research-rotation-original.gif`. Nothing was re-encoded or regenerated.

**Limitation: smooth *and* slow dissolves are not possible with delays alone.** With four in-between frames, any dissolve longer than a fraction of a second shows four visible double-exposure stages; the Chromium strip of the 13.3–14.9 s transition shows this. Truly smooth slow dissolves need about 10–20 interpolated blend frames per scene change, which means re-encoding. A GIF with that many extra frames would grow by roughly 1 MB per 12 added frames at the current frame size. Converting to WebM/MP4 would be smaller but changes the asset type and the `<picture>` markup. Neither was done; both need your approval first.

### Border diagnosis and blend change

**Diagnosis from inspection:**
- **The border is not in the GIF.** Its outermost 3 px rows and columns vary like normal image content (stddev 58–84 per channel), and its edge colours are warm dark brown (mean `#5c493d` over all frames; per-scene edges range from `#2e211a` to `#a79178`, the lighter right edge being window light).
- **The pale frame came entirely from the CSS card.** Chromium computed styles at 1440×900 showed: `.login-visual-card` with background `linear-gradient(145deg, rgb(244,238,228), rgb(226,221,210))`, 14 px padding, a 1 px border, a `0 28px 80px` shadow and a pale caption area; and `.login-visual-picture` with background `rgb(216,208,194)`.
- **The panel behind the card** is a cool-teal radial gradient (`#263c3b → #1a2a2e → #142126`) on the page's `#101b21` background.

**CSS change** (`frontend/src/styles.css`, login visual rules only):
- `.login-visual-card` is now a transparent layout wrapper: no background, padding, border, radius or shadow. Its width is `min(100%, 47.2vh, 496px)`, the same artwork size as before.
- `.login-visual-picture` has no background or radius. A two-axis eased (smoothstep-shaped) mask feathers the artwork into the panel: 16% fade on the left, right and top, 24% at the bottom so it flows into the caption.
- `.login-visual` gains one low-opacity warm radial glow (`#3b302880` → `#2e2b2740` → transparent) behind the artwork, layered over the unchanged teal gradient. It bridges the warm artwork and the cool panel without a visible shape.
- Caption colours are switched for the dark background: label `#6dc8aa` (the same green as the existing `.login-eyebrow`), text `#dfe8e5`. Size, weight and copy are unchanged.

LoginPage markup, the form, the reduced-motion poster, the image-error fallback and the ≤900 px behaviour are unchanged.

### Visual verification performed

Isolated Vite dev server on `127.0.0.1:4319` (API proxy target the isolated `127.0.0.1:8001`), headless Chromium.
- **Before/after screenshots at 1440×900 and 390×844, reviewed by eye.** The pale card and frame are gone. The artwork fades into the panel with no rectangle, frame or shadow.
  - A first 7–9% linear feather still showed a straight top edge over the bright window. A 12% linear version was measurably softer but still had a visible onset. The final eased 16%/24% feather was chosen after edge crops at 2× enlargement.
  - The soft vertical light at the right edge is the artwork's own window light fading out.
- **Desktop geometry:**

  | Viewport | Artwork size | Panel gutters (left / right) | Ratio |
  |---|---|---|---|
  | 1920×1080 | 496×620 | 232 / 232 px | 0.8 |
  | 1280×720 | 340×425 | 150 / 150 px | 0.8 |
  | 1024×768 | 362×453 | 75 / 75 px | 0.8 |
  | 2560×1440 | 496×620 | 392 / 392 px | 0.8 |

  There was no horizontal overflow. At 1280×720 the page scrolls vertically because the left form panel ends at 788 px; that is pre-existing. The artwork block ends at 669 px.
- **Tablet and mobile (820×1180, 390×844):** the artwork is hidden as before and the form is fully visible with no overflow. The mobile screenshot was reviewed.
- **A full loop watched in the page.** The rendered artwork region was captured every ≈117 ms for 100 s (`currentSrc` = the GIF, reduced motion off).
  - 62 frame changes were observed, with intervals of about 1.63–1.77 s (holds), 0.70–0.86 s (dissolve steps) and 3.96–4.10 s (arrivals).
  - 60 consecutive changes spanned **94.23 s**.
  - A six-frame strip of one transition (last hold, four dissolve stages, arrival) was reviewed by eye. The holds read as near-still with a very slow drift. The dissolve reads as a slow cross-fade but in four visible stages, which is the limitation above. The feathered edges and caption stay stable throughout.

### Files changed in this refinement

- `frontend/public/images/ekip-login-research-rotation.gif` (delay bytes only)
- `frontend/src/styles.css` (`.login-visual`, `.login-visual-card`, `.login-visual-picture` and the caption colour/padding rules only)
- `frontend/e2e/smoke.spec.ts`:
  - delays updated to the new pattern, total 9,420 cs;
  - the layout test now asserts no card background, padding, border or shadow, a transparent picture background, a feather mask, symmetric gutters (≤ 1 px difference) and a light caption colour, replacing the old "padding ≤ 14 px" check.
- this report

### Verification run for this refinement

| Command | Result |
|---|---|
| `npx vitest run src/App.test.tsx` (from `frontend/`) | PASS: 1 file, 13 tests |
| `EKIP_API_PROXY_TARGET=http://127.0.0.1:8001 npx playwright test e2e/smoke.spec.ts` (from `frontend/`) | 2 passed, 1 skipped (live login: no synthetic credentials), 0 failed |
| `npm run check` (from `frontend/`) | PASS (`tsc --noEmit`, no errors) |
| `git diff --check -- frontend/src/styles.css` | PASS |
| `git diff --no-index --check /dev/null frontend/e2e/smoke.spec.ts` (untracked file) | No whitespace issues |
| Same check on this report | Only the pre-existing Markdown hard line breaks on header lines 3–5 |

Checks not run, and why:
- Full Vitest suite, production build and full E2E suite: not run, because the change is limited to the login asset, login CSS and smoke test.
- Cross-browser rendering (Safari/Firefox) of `mask-image` / `mask-composite`: not checked. A `-webkit-` prefixed mask is included as a fallback.
- Credential-based login E2E: skipped by its guard because no synthetic credentials are set.

No production API (port 8000), `data/` content or secrets were accessed. The temporary dev server was stopped and ports 4319 and 4173 were confirmed closed.

## Final speed correction — 2026-10-16 (historical; superseded by the section above)

**Problem.** At 27 s per loop (60 frames × 450 ms) the animation still looked too fast. Frame analysis showed why. The GIF is six distinct scenes of 10 frames each:
- frames 0–5 of each scene are a slow push-in hold (mean blurred frame-to-frame change ≈ 3.4);
- frames 6–9 cross-dissolve into the next scene (change ≈ 12–16 per step, with the largest step landing on the next scene's frame 0).

With uniform delays, each scene was fully visible for only 6 × 0.45 s = 2.7 s before it began dissolving.

**Change (delays only).** The new per-scene delay pattern, repeated for all 6 scenes, is `[150, 100, 100, 100, 100, 100, 60, 60, 60, 60]` centiseconds:
- 1.5 s on the clean arrival frame;
- 1.0 s on each push-in hold frame;
- 0.6 s on each of the four dissolve steps, giving a measured 2.4 s cross-dissolve.

Each scene lasts 8.9 s and is fully visible for 6.5 s, which is 2.4× the previous 2.7 s. Holds get the longest delays because their per-frame change is small. Dissolve steps stay short enough to read as a dissolve rather than a slideshow.

**Measured result** (block-aware GIF parser over the output file, plus `ffprobe`):

| Property | Before this correction | After |
|---|---|---|
| Frames | 60 | 60 (same order) |
| Delays | 60 × 45 cs | 6 × 150 cs, 30 × 100 cs, 24 × 60 cs |
| Loop duration | 27.00 s | **53.40 s** (`ffprobe` duration 53.400000) |
| Scene duration | 4.5 s | 8.9 s per scene (all six) |
| Dimensions | 400×500 | 400×500 |
| Loop extension | NETSCAPE2.0, infinite (0) | Unchanged |
| Disposal | 2 on all frames | Unchanged |
| File size | 5,280,679 bytes | 5,280,679 bytes |
| SHA-256 | `926ae7a3…7ceb` | `8b1821fd474209a2052a3ca8c9d5ab604da391af537441be8bc47811883adc7b` |

A byte comparison against both the pre-correction file and `ekip-login-research-rotation-original.gif` found 0 changed bytes outside the 60 two-byte Graphic Control Extension delay fields. Pixels, palette and LZW data were not re-encoded, and no frames were dropped or added. The original backup is untouched (SHA-256 `670ceecc…849b`, 60 × 10 cs = 6.0 s).

**Real-page playback.** The Vite dev server ran on isolated port 4319 and headless Chromium loaded the actual login page at 1440×900. `currentSrc` was the GIF and `prefers-reduced-motion` was false. The rendered `<img>` was screenshotted about every 166 ms for 58 s.
- Observed on-screen intervals: about 1.0 s holds, 0.49–0.69 s dissolve steps (0.6 s, quantised by the sampling interval) and 1.48–1.65 s arrivals.
- 60 consecutive frame changes spanned **53.42 s**.

This confirms the browser plays the new timing as intended. It does not replace a human judgement that the animation feels cinematic, which is the remaining sign-off item.

**Earlier text inconsistency.** The "Small correction" section below says the GIF previously had a 15 s loop at 250 ms per frame. The measured original backup is 100 ms per frame (6.0 s), consistent with the Summary section. The 250 ms figure could not be reproduced from any file present.

**White border, which was still clearly incorrect.** The card had a fixed `width: min(100%, 540px)`, but the artwork is capped at `min(100%, 47.2vh, 496px)` and was left-aligned. On any viewport shorter than about 1,050 px, the card showed a one-sided pale strip: 15 px on the left and about 100 px on the right at 1440×900. The single CSS change in `.login-visual-card`:
- moves the existing padding value into `--login-visual-pad` (still `clamp(8px, 1.2vw, 14px)`);
- sets the card width to `min(100%, calc(min(47.2vh, 496px) + 2 * var(--login-visual-pad) + 2px))`, so the card shrinks to the artwork.

Padding, radius, colours, caption and the form are unchanged.

Browser measurements of the frame gutters (left / right / top) after the change:

| Viewport | Gutters | Artwork ratio |
|---|---|---|
| 1440×900 | 15 / 15 / 15 px | 0.8000 |
| 1280×720 | 15 / 15 / 15 px | 0.8000 |
| 1920×1080 | 15 / 15 / 15 px | 0.8000 |
| 1024×768 | 13.3 / 13.3 / 13.3 px | 0.8000 |
| 2560×1440 | 15 / 15 / 15 px | 0.8000 |
| 1440×1200 | 15 / 15 / 15 px | 0.8000 |

The card did not overflow the viewport at any of these sizes. The tablet/mobile behaviour of hiding the artwork at 900 px and below is unchanged.

**Files changed in this correction:**
- `frontend/public/images/ekip-login-research-rotation.gif` (delay bytes only)
- `frontend/src/styles.css` (the `.login-visual-card` rule only)
- `frontend/e2e/smoke.spec.ts` (expected delays updated to the scene pattern, plus an assertion that the delays total 5,340 cs)
- this report

**Verification run for this correction:**

| Command (from `frontend/`) | Result |
|---|---|
| `npx vitest run src/App.test.tsx` | PASS: 1 file, 13 tests |
| `EKIP_API_PROXY_TARGET=http://127.0.0.1:8001 npx playwright test e2e/smoke.spec.ts` | 2 passed, 1 skipped (live login: no synthetic credentials), 0 failed. The served GIF passed the new delay, frame-count, dimension and loop assertions, and the desktop/tablet/mobile layout test passed. |
| `npm run check` | PASS (`tsc --noEmit`) |
| `git diff --check -- frontend/src/styles.css` | PASS |

Checks not run, and why:
- The full Vitest suite, production build and full E2E suite were not run; this was a focused correction.
- A standalone `tsc` of the E2E spec could not run because `@types/node` is not installed. Playwright compiled and executed the spec successfully.
- The Playwright smoke test only reached the isolated loopback API on port 8001, which returns an unauthenticated 401 for a protected route. No production resource or `data/` content was touched.

The temporary dev server on port 4319 was stopped after measurement. Ports 4319 and 4173 were confirmed closed.

## Small correction — 2026-10-16 (historical; timing superseded above)

The active GIF had a 15-second loop (60 frames at 250ms each). This correction changes only the Graphic Control Extension delays from 250ms to 450ms, producing a verified 27.0-second loop. The 60 frames, frame order, 400×500 dimensions, encoded frame payload, colour data, loop extension, and 5,280,679-byte file size are unchanged. The preserved original backup remains untouched.

The apparent white border is not part of the GIF. It is the pale `.login-visual-card` background revealed by its inner padding. The card padding is reduced from `clamp(14px, 2.1vw, 24px)` to `clamp(8px, 1.2vw, 14px)` and its corner radius from 24px to 20px. This keeps a deliberate light frame while making the proportional artwork larger. No login form, authentication, colour, or unrelated layout rule changed. The image container width now derives from the same 59vh height budget (`47.2vh`) so it retains its exact 4:5 ratio after the larger available content width.

## Summary

The login artwork previously filled and cropped across the right half of the viewport. It now sits inside a centered, padded card with a warm frame and refined dark-green background. The image retains its 4:5 aspect ratio and uses `object-fit: contain`. On tablet widths (820px) and mobile (390px), the decorative artwork is hidden so the form has room. The login copy, fields, password visibility control, submission and error handling are unchanged.

The animated GIF was 400×500, 60 frames, 100 ms per frame, and a 6-second loop. Every frame now lasts 450 ms (4.5× the original interval), making the final loop 27 seconds. All 60 frames remain in their original order; only each Graphic Control Extension delay was changed. No pixels were recompressed or frames dropped. The active GIF remains 400×500 and 5,280,679 bytes. A byte-identical original is retained alongside it. The repository’s 960×1200 poster was evaluated; it is a separate still moment, not a higher-resolution animation source, and remains the reduced-motion image.

## Asset measurements

| Asset | Before | After | Notes |
|---|---|---|---|
| `ekip-login-research-rotation.gif` | 400×500; 60 frames; 100ms/frame; 6.0s; 5,280,679 bytes | 400×500; 60 frames; 450ms/frame; 27.0s; 5,280,679 bytes | Pixel/frame payload and order preserved; GIF loop extension retained. |
| `ekip-login-research-rotation-original.gif` | Did not exist | 400×500; 60 frames; 100ms/frame; 6.0s; 5,280,679 bytes | Byte-for-byte copy of the original source asset. |
| `ekip-login-research-rotation-poster.jpg` | 960×1200; 195,616 bytes | Unchanged | Existing reduced-motion image; higher resolution but not an animation source. |

Measurements used `file`, `ffprobe`, a block-aware GIF timing update/verification script, and the Playwright asset parser. The parser verified all 60 frame delays at 45 centiseconds and the looping extension in the served file.

## Changed-file inventory

Files changed for this refinement:

- `frontend/src/LoginPage.tsx` — group artwork and caption in a contained visual card; preserve `<picture>` reduced-motion source and the existing error fallback.
- `frontend/src/styles.css` — existing balanced desktop split, a now narrower 8–14px visual-card frame, exact 4:5 contained sizing, and existing single-column form layout at tablet/mobile widths.
- `frontend/public/images/ekip-login-research-rotation.gif` — same frame data, updated delays only.
- `frontend/public/images/ekip-login-research-rotation-original.gif` — new byte-identical original backup.
- `frontend/e2e/smoke.spec.ts` — inspect served GIF dimensions, delays, frame count and loop; assert reduced-motion poster dimensions and responsive artwork/form layout.

These paths were already part of a dirty/untracked Task 04/05 working tree when this task began (`LoginPage.tsx`, the active GIF, and E2E test were untracked; `styles.css` was already modified). The report archive’s patch therefore includes the consolidated tracked `styles.css` diff; it is not a clean task-only patch. See `git-status.txt` and `git-diff.patch` in the archive. Existing Task 04/05 work and reports were preserved. No `data/`, `.env`, production service, or production volume was read or changed.

## Acceptance matrix

| Criterion | Result | Evidence / limitation |
|---|---|---|
| Animation feels noticeably slower, with 24–30 second loop | SUPERSEDED | 27 s still looked too fast in the page; replaced by the 45–60 s criterion below. |
| Loop is 45–60 s and the scenes are held long enough | SUPERSEDED | 53.4 s still felt fast; replaced by the cinematic-timing rows below. |
| Loop about 80–100 s, with long calm holds and a slower push-in (delays-only) | SUPERSEDED | Replaced by the interpolated 100 s GIF (rows below). Previously measured: | 94.20 s from metadata; 94.23 s observed in Chromium; 12.5 s fully visible per scene; the push-in spans 12.5 s instead of 6.5 s. |
| Dissolves slower and smooth rather than stepped (delays-only) | SUPERSEDED (was PARTIAL) | Slower (2.4 s → 3.2 s), but still four visible stages; smooth would need interpolated frames, i.e. re-encoding, which awaits approval. |
| Animation visibly feels slow and cinematic in the login page | NOT VERIFIED (human) | Timing and transitions were watched in Chromium; the subjective acceptance needs your review. |
| All 60 frames, artwork, dimensions, quality and infinite loop preserved | PASS | 0 non-delay bytes changed (image, palette and LZW data byte-identical); 400×500; NETSCAPE loop retained; same file size. |
| Pale frame is even and not excessive | SUPERSEDED | The card frame was removed entirely (row below). |
| No artificial border; artwork blends into the panel (feathered) | SUPERSEDED | Replaced by a subtle tonal frame, per the final request. Previously: | Computed card frame is none/0 and feather mask present (Playwright); symmetric gutters at four desktop sizes; screenshots reviewed. Final aesthetic acceptance is yours. |
| Readability and contrast elsewhere preserved | PASS | Form unchanged; caption is light (`#dfe8e5`) on the dark panel; tablet/mobile unchanged. |
| Final: loop about 100 s, with slow push-in and calm, smooth dissolves | PASS (measured, browser-observed) | 100.00 s metadata; 99.93 s loop re-match in Chromium; 360 frames; largest step 3.7 (was about 23); 5 s dissolves; 13-frame transition strip reviewed. |
| Final: artwork, six-scene order, 400×500, 4:5 and infinite loop preserved; GIF format kept | PASS | Original frames are the interpolation anchors (arrival-frame PSNR 43.9 dB); NETSCAPE loop 0; no frontend markup change. |
| Final: file reasonably optimised | PASS with trade-off | 18.09 MB, against 36.6–50.7 MB for standard encodes; 3.4× the original 5.3 MB. |
| Final: small, subtle border; balanced spacing; colours blended with the interface | PASS (measured) / NOT VERIFIED (human) | 6 px tonal mat plus 1 px hairline; equal 7 px insets; symmetric gutters at four desktop sizes; mat about 75% panel and 25% artwork tone; screenshots reviewed. |
| Final: the animation visibly feels slow and cinematic, and the frame looks right | NOT VERIFIED (human) | Awaiting your review in the login page. |
| Artwork is not over-zoomed, stretched, or edge-to-edge | PASS | CSS `object-fit: contain`; exact 4:5 card geometry assertion; screenshot visually reviewed at 1440×1000. |
| Pale border is noticeably smaller while retained | PASS | The card padding is reduced from 14–24px to 8–14px; a browser assertion confirms the applied desktop padding is at most 14px. |
| Desktop split is balanced and polished | PASS | Browser geometry and captured desktop screenshot show form as primary focus and artwork within the right-side padded card. |
| Login remains readable on tablet/mobile | PASS | Browser checked form visibility and no horizontal overflow at 820×844 and 390×844; artwork hides at these widths. |
| Reduced-motion preference displays poster | PASS | Browser changed media preference to `reduce`; `currentSrc` changed to poster and intrinsic size was 960×1200. |
| Missing GIF and poster do not break login | PASS | Existing component fallback and Vitest regression test simulate both image errors; form remains usable. |
| Authentication behavior remains intact | PASS with live-test limitation | Frontend suite passed, including login/auth regression tests. Credential-based live login E2E was skipped because the E2E credential variables were not configured for this run. |
| Requested automated checks | PASS / PARTIAL | TypeScript, Vitest, and build passed. E2E had two visual/proxy passes and two credential-dependent skips; no E2E failures. |

## Verification evidence

Commands ran from `frontend/` unless noted:

| Exact command/action | Actual result |
|---|---|
| `npm run check` | PASS, `tsc --noEmit`, exit 0. |
| `npm test -- --reporter=dot` | PASS, 4 files and 90 tests passed, exit 0. |
| `npm run build` | PASS, TypeScript plus Vite production build, 38 modules transformed, exit 0. |
| First `npm run test:e2e` after reducing padding | 1 passed, 1 failed, 2 skipped. The new wider content area hit the old fixed maximum height, making the image container ratio 0.864 rather than 0.8. The failure was corrected by deriving width from the 59vh height budget. |
| Final `npm run test:e2e` | 2 passed, 2 skipped, 0 failed. Passed: proxy/login visual smoke and layout at desktop/tablet/mobile. Skipped: managed live profile/logout and full live workspace flow because `EKIP_E2E_LOGIN_EMAIL` / `EKIP_E2E_LOGIN_PASSWORD` were not supplied. No credentials were read from `.env`. |
| `git diff --check` (repository root) | PASS, exit 0. |
| `file frontend/public/images/ekip-login-research-rotation.gif frontend/public/images/ekip-login-research-rotation-poster.jpg` | Before edit: GIF 400×500; JPEG 960×1200. |
| `ffprobe -v error -select_streams v:0 -show_entries stream=width,height,nb_frames,duration -show_entries format=size -of json frontend/public/images/ekip-login-research-rotation-original.gif` | Original backup: 400×500, 60 frames, 6.000000 seconds, 5,280,679 bytes. |
| Same `ffprobe` command against `frontend/public/images/ekip-login-research-rotation.gif` | Final GIF: 400×500, 60 frames, 27.000000 seconds, 5,280,679 bytes. |
| One-off Chromium screenshot at 1440×1000 | PASS, login rendered and screenshot was reviewed; temporary screenshot stayed under `/private/tmp` and is not in the archive. |

Playwright reported only Node/Vite `NO_COLOR`/`FORCE_COLOR` warnings. This task did not call the API for login and did not contact production. The browser visual test uses the frontend’s isolated proxy configuration; API-bound visual smoke checks use port 8001 only.

## Known limitations

- The current run did not execute credential-based live login/profile/logout or the full document/query workspace flow. They were skipped by the checked-in test guard because no in-process synthetic credentials were configured. The UI implementation and mocked auth regressions passed; the previously recorded live flow is historical evidence, not a fresh result for this refinement.
- No high-resolution animated source exists in the inspected frontend assets. The separate 960×1200 poster is retained for reduced motion; animation resolution stays at 400×500 rather than being upscaled.
- GIF file size remains 5.28 MB because frame encoding and visual data were intentionally preserved with no lossy recompression.
- No production checks, container changes, or database changes were needed or performed.
- PDF report generation was omitted; Markdown is the review source of truth.

## Git snapshot and continuation

Current branch is `feature/organisation-knowledge-management`; HEAD remains `fabb5b2c0d591a6408da2ec7ac66feeb5d69298b`. The worktree remains dirty with the previously existing Task 04/05 changes plus this refinement. The full current status is included in the review archive. No files were staged; no commit, push, reset, clean, stash, or branch change occurred. The aggregate tracked diff includes earlier work and is not a measure of this refinement alone.

The next step is visual approval of this focused correction. Do not create a broader repository snapshot or begin another roadmap feature as part of this task. If authenticated E2E evidence is required, run `npm run test:e2e` from `frontend/` with an approved synthetic account supplied only to the process environment and the existing isolated test service; do not load or print `.env` values.
