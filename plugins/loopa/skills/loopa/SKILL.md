---
name: loopa
description: >-
  Loopa (read "lupa", Indonesian for "forget": forget hand-editing loops). Turns a folder of raw footage (one
  clip, many clips, sorted into subfolders or dumped loose and mixed) into as many distinct, seamlessly LOOPING
  viral shorts as the footage supports (TikTok, Reels, YouTube Shorts; each at its natural length, mostly 9–20
  s, ceiling 30 s). Every video is a re-created edit, not a trim, with its own format, POV/angle, hook,
  narration, look, and sound, and every video loops end-to-start by default. It scans and groups footage
  automatically, offers a library of 15 viral formats (result-first, POV story, velocity, satisfying loop,
  transformation, listicle, myth vs fact, quiz, ASMR, montage, timelapse, count, ranked compilation, kinetic
  story, split screen), renders in batch with anti-duplicate checks, applies an anti AI-slop checklist, and does
  Indonesian voice-over dubbing (Kokoro) with karaoke captions. Use it whenever the user wants
  shorts/reels/konten sosmed from video, "re-create", "edit ulang", "recycle footage", "bikin video viral",
  "sebanyak-banyaknya video", kompilasi, looping videos, a folder of raw clips to process, a dubbing/narasi
  version, or says an existing edit looks low-effort, even if they don't name any of these tools.
---

# Loopa

*Read "lupa": forget hand-editing loops.* Drop raw footage in a folder; Loopa re-creates it into many distinct shorts that loop seamlessly in picture and sound.

The standard: **every video loops seamlessly, music-first**: the soundtrack is an N-bar musical cycle (drop on bar 0, build on the last bar, rendered tail-to-front so it is exactly periodic), and the video is cut to exactly those bars, so on replay both picture and sound simply keep going, **every video runs at its natural length** (mostly 9–20 s, ceiling 30 s; shorter is better whenever it reads naturally), and the footage is **recycled into as many distinct shorts as it supports**. The code enforces both: every format ends with a loop bridge, and `--check` blocks near-duplicates. For a new channel, quantity matters, but near-identical reposts get an account labeled "unoriginal" (Instagram stops recommending such accounts since April 2026). So each video changes the format, angle, first 2 seconds, copy, look, and sound.

Everything renders locally (ffmpeg, OpenCV, Pillow, numpy, scipy). Music and SFX are synthesized, so they carry no copyright risk. Real footage of real hands is the anti-slop advantage, so protect it.

## Files

| file | what |
|---|---|
| `scripts/scan.py` | scan a footage folder: group clips into units (subfolder = unit; loose clips clustered by capture time + look), per-clip analysis (cached), contact sheets, scene cuts, draft moments |
| `scripts/build_all.py` | run every unit's plan (and cross-unit `_all`) sequentially, resumable; `--merge` pools all units' moments; writes `manifest_all.csv` |
| `scripts/build.py` | one plan: `--check` (length 4–30 s, loop, diversity), render, `manifest.csv` |
| `scripts/formats.py` | 15 format builders + the mandatory loop bridge |
| `scripts/kits.py`, `music.py` | 6 type kits with auto-fit; 6 music styles × key × seed |
| `scripts/engine.py` | render core: speed ramps, AI slow motion, shutter motion blur, camera, split screen, seamless loop, multi-footage, any fps/orientation |
| `scripts/framegen.py`, `setup_rife.sh` | **AI frame generation** (RIFE v4.26 on the GPU via ncnn/Vulkan): every slower-than-realtime frame is a newly generated in-between frame |
| `scripts/captions.py`, `make_vo.py`, `tts_id.py`, `voice_test.py`, `setup_tts.sh` | dubbing |
| `scripts/loopa` | **entry point**: `loopa doctor | scan | check | build | build-all | preview | seam | sheet`. It picks the Python with the deps (`$LOOPA_PY` > `~/.loopa/venv` > `python3`). Always call the tools through it. |
| `scripts/contact_sheet.sh`, `loop_check.sh`, `loop_preview.sh` | QC grids; loop seam score; `loop_preview.sh X.mp4 3` writes the video 3× back-to-back into one file, which is how to *watch* a loop (player repeat modes like VLC's reopen the file and add a hitch to every video). No official TikTok/Reels/Shorts simulator exists, so the final check is a private/draft upload. |
| `references/viral-formats.md` | **read when planning**: formats, copy keys, footage fit, looping, multiplying footage |
| `references/anti-slop.md` | **read before writing copy, and at QC** |
| `references/dubbing.md` | Kokoro Indonesian, voice scores, anchored VO lines |
| `references/engine-api.md` | only for new formats / deep customization |
| `references/editing-playbook.md` | hooks, text sizes, safe zones, audio |
| `examples/oat-fried-rice/` | a real moments.json + an 18-video plan.json that rendered and looped |

## Workflow

### 0. Scan the folder

```bash
<skill>/scripts/loopa doctor                                   # once: ffmpeg, python packages, RIFE, TTS, fonts, disk
<skill>/scripts/loopa scan <footage_root> [--exclude short,old_edits]   # workspace: <footage_root>/_shorts
```

- **A subfolder with videos = one unit** (the user already grouped it). Its clips become `c1, c2…` of one project, and moments can come from any of them.
- **Loose videos in the root may be an uncategorized mix.** `scan.py` proposes groups in `_shorts/groups.json` (same recording session + similar look + filename sequence) and draws `_shorts/roster.jpg`, one row of thumbnails per clip. **Look at roster.jpg and fix groups.json**: move clips, give groups meaningful ids (they become workspace names), put junk in `skip`, set `"reviewed": true`, then rerun `scan.py`. It reuses the cached analysis, so the rerun takes seconds.
- Exclude folders of old edits or outputs (`--exclude`). Folders starting with `_` or `.` are skipped automatically.
- Output: `_shorts/units.json` and, per unit, `footage.json`, `moments.draft.json`, and overview sheets (paths in `units.json`).

Keep everything in the workspace, never in `/tmp`: a crash or reboot wipes temp dirs. Check `ffmpeg` and `python3 -c "import cv2, PIL, numpy, scipy"`. Kits fall back to Avenir Next for missing fonts.

**Set up slow motion once:** `install.sh --with-rife` (or `bash <skill>/scripts/setup_rife.sh ~/.loopa/rife`). `~/.loopa/rife` is auto-detected, and a plan's `rife_python` or `$LOOPA_RIFE_PY` overrides it. If it's missing, check whether the user ran the installer with `--with-rife`, and offer to run `setup_rife.sh` (it downloads ~22 MB of models). Slow motion must look like real high-frame-rate footage, never a stretched 30 fps clip with repeated or ghosted frames. With RIFE, every frame below 1.0x is a generated frame (about 0.3–0.4 s per 1080×1920 frame, cached). Fast ramps (≥ 1.8x) get shutter-blended motion blur so they feel filmic. Without `rife_python`, the build warns and falls back to OpenCV optical flow below 0.7x. Treat that as a degraded mode and tell the user.

**Render only one thing at a time.** Each render takes about 0.5–1 GB, and parallel renders crashed an 8 GB Mac during development. All builders are sequential and resumable (rerun after any interruption and finished files are skipped; files are written as `*.part.mp4` and renamed on success).

### 1. Map each unit → `moments.json`

Start from `moments.draft.json`, which has one `todo` moment per detected shot in clip order. Look at the overview sheets. Tiles are 1 per second (0.5/s for clips over 2 min), 10 per row, so tile *n* ≈ second *n*. Zoom in with `contact_sheet.sh CLIP x.jpg 4 12 <start> <dur>`. Then:
- Set `kind` (before | action | process | result | reveal | macro | skip), `label` in the user's language, `hit` for actions, `focus` [cx, cy] for off-center subjects, and `hero: true` for the twist. Split long shots into separate moments.
- For horizontal clips, set `footage.cN.crop` [cx, cy] so the 9:16 crop lands on the subject.
- **Every moment must sit inside one shot.** Raw footage is often an edit itself (the oat example has 17 hidden camera cuts). Use the detected cuts (`footage.cN.cuts`, from scan.py) and split any moment that spans one. `build.py --check` fails on a segment that crosses a cut. Don't hand-type `lead_in`: it's derived from the cuts. A guessed value made a loop bridge reach into a different camera angle (a visible jump at the loop) in development.
- Use only the in-focus span (macro shots often blur at the end). Order `process_order` chronologically.
- Raw footage audio is usually quiet ambience (see `loudness_db_per_s` in footage.json).

### 2. Research (quick)

Run 1–2 web searches for current trends in this niche, and keep the sources for the report.

### 3. Plan → `plan.json` per unit, plus `_all/plan.json` across units

Read `references/viral-formats.md` and `references/anti-slop.md`.
- Per unit: every format that fits the footage, one video each, each with a distinct **angle/POV**, then extra loops of standout actions, then **dubbed variants** of the 2–3 strongest (`vo` + `variant_of`).
- Across units: `build_all.py WS --merge` writes `_all/moments.json` (ids `<unit>.<moment>`). Plan ranked compilations, "best of" montages, or series that mix units in `_all/plan.json`.
- Vary `kit`, `grade`, `music`, `key`, `seed`, and the opening (`hook_moment` / `rotate`). Write the `copy` (casual, specific, true to the footage, ≤ 1 emoji, no banned phrases). Disclose fictional framings to the user. Add `post.caption` and `post.hashtags`.
- Length: each format has a **natural length** (`formats.NATURAL`). Visual/rewatch formats (quiz, loops, montage, split, velocity) run 9–15 s, the 2026 "viral sweet spot" with the highest completion (esp. Reels). Formats that carry information or a story (listicle, myth vs fact, kinetic story, POV, dubbed) run 16–20 s, the strongest TikTok engagement band, with Shorts completion peaking around 20–25 s. `finish()` re-times the whole edit uniformly (cuts, text, effects, music tempo; ±35% max) to land there. Override with `target_s` per video only when the content wants it (a voice-over that needs room, a story that needs a beat more), never to pad. Ceiling: plan `max_s` (default 30). Hooks and retention matter far more than length.
- The plan's `moments`, `out_dir`, and `tmp_dir` are relative to the plan file. Dubbing needs the TTS env: `install.sh --with-tts` (or `setup_tts.sh ~/.loopa/tts`), auto-detected; `tts_python` / `$LOOPA_TTS_PY` override.
- Typical yield: about 15–20 videos per minute-plus unit with a clear result. Short or simple units yield fewer, so don't pad.

### 4. Check, then render

```bash
<skill>/scripts/loopa build-all <WS> --check     # fix every ✗ in every unit
<skill>/scripts/loopa build-all <WS>             # long: run in the background, wait for the notice
```

For a single unit, run `loopa build <unit>/plan.json [--only id1,id2] [--force]` (`--audio-only` re-mixes the soundtrack of finished videos in seconds). Before a big batch, render 2–3 risky videos (dubbing, split, timer) and QC them first.

### 5. QC every render (don't skip)

- Make a grid with `contact_sheet.sh OUT.mp4 qc.jpg 3 10 0 "" 150`, and check for text overflow, overlapping captions, blurry hook frames, wrong labels, and VO that doesn't match the picture.
- **Loop seam (picture and sound)**: run `loop_check.sh OUT.mp4 seam.jpg` (video "OK seamless", audio "OK smooth"), then watch `loop_preview.sh OUT.mp4 3`. The soundtrack is **music-first**: an N-bar cycle (drop on bar 0, build on the last bar, chords resolving into the top) rendered tail-to-front, so it's exactly periodic with no crossfade. The video is cut to exactly N bars.
- To fix only the soundtrack of finished videos (music, mix, loop audio), use `build.py plan.json --audio-only`. It rebuilds and remuxes in seconds without re-rendering the picture. Dubbed videos whose voice timing changed are flagged for a full `--force` re-render, because their captions are burned in.
- **Slow motion**: the build log must show `framegen: generated N frames` (not the fallback warning). Spot-check 6 consecutive slow-mo frames (`ffmpeg -i X.mp4 -vf "select='between(n,40,45)',scale=300:-1,tile=6x1" -frames:v 1 s.jpg`): motion should advance a little each frame, with no doubled edges and no repeats.
- In the dubbing log, read what Whisper heard. Rewrite lines that come out garbled or are flagged `!!` (too long for their window).
- Loudness is normalized to -14 LUFS automatically. Audio is 48 kHz, and every video's length is snapped to a multiple of 16 frames (= whole AAC blocks), so the AAC soundtrack has no encoder padding at the loop seam. Padding would decode as ~1.6 ms of silence, which clicks on every replay. The soundtrack is also locked sample-exact to the frame count.
- Go through the anti-slop QC gate. Fix, re-render with `--only … --force`, and look again.

### 6. Report

Give a table per unit (file, format, angle, seconds, dubbed), point to `manifest_all.csv` (captions + hashtags), and list fictional framings and creator-voice claims. Add posting advice: spread formats and units across days, post variants days apart, and swap in a trending sound in-app for non-dubbed uploads. Explain how to add footage later: drop clips in the folder, rerun `scan.py` (new loose clips get flagged), then plan → build_all. Cite the trend sources.

## Extending

New format: add a function to `formats.py` that returns `finish(...)` (the loop bridge is applied there, so it loops automatically), register it in `FORMATS`, and document it in `viral-formats.md`. Per-segment effects are flags (`fx={'punch','whip','pulse'}`) so they stay motivated, not uniform. See `references/engine-api.md`.
