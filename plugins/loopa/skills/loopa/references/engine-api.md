# engine.py API

Most work goes through `build.py` + `formats.py`. Read this only when writing a new format.

Slow motion: `render(..., framegen={'py': rife_python, 'model': <env>/rife-models/rife-v4.26, 'dir': cache})` collects every frame played below 1.0x, runs `framegen.py` once in the RIFE env (GPU, ncnn/Vulkan) to generate the exact in-between frames (source pair + timestep), caches them, and reads them back during the render. Frames at ≥ `SHUTTER_FROM` (1.8x) blend the 2–5 source frames they span (shutter motion blur). Without framegen it falls back to DIS optical flow below `smooth_thresh` (0.7).

New in volume mode:
- `Seg(..., src=path)` uses any footage file, so one timeline can mix clips (compilations). Frames are cover-cropped to 1080x1920 automatically.
- `Seg(..., split=Seg(...), split_mode='v'|'h')` puts a split screen in the segment (top/bottom or left/right center crops with a white divider).
- `render(..., loop_blend=s)` + `loop_audio(mix, s)` make a seamless loop: the first `s` seconds are dissolved into the tail and the output starts after them.
- `formats.seg(M, moment, dur, mode, cam, fx)` builds a Seg from a moment. Modes: normal | span | slow | velocity | slowhit | snap | freeze. Profile modes align the slow-mo with the moment's `hit`.
- `formats.fit_to_target(...)` (called by finish) uniformly re-times a format to `formats.TARGET['s']` (set from plan `target_s`). B, overlays, hits, and music drop all scale together.
- `formats.finish(segs, B, overlays, hits, reveal, freeze, music, grade, extra, loop, nat)` returns a spec. `build.make_audio` turns that spec into the mix (music bed, SFX budget, natural sound, VO ducking, loop).

All coordinates are normalized (0..1) to a 1080x1920 frame. Times are in seconds. Import with `from engine import *` after `sys.path.insert(0, <dir of engine.py>)`. The source clip comes from the `SHORTS_SRC` env var.

## Timeline

```python
Seg(a, b, dur, speed=None, cam=None, reverse=False, tag=None)
```
- `a, b`: source in/out (s). `dur`: output duration (s). Use beat multiples like `2*B`.
- `speed`: keyframes `[(u, rel_speed), ...]` over u ∈ [0,1]. They shape the time map, so the segment still spans a..b in `dur`. Effective rate = (b−a)/dur × normalized keyframe. Rates below 0.7 use DIS optical-flow interpolation (smooth slow-mo).
- A freeze frame is `Seg(t, t+0.01, dur)`.
- `cam`: `zoom0/zoom1` (≥1), `cx0/cy0/cx1/cy1` (centre), `rot0/rot1` (deg), `ease` ∈ io|out|in|lin. Zoom >1 also gives headroom for shake and rotation without black borders.
- `tag`: free label, used by your `fx` function and audio logic.

`Timeline(segs)` gives you `.dur`, `.starts` (cumulative start times; `S[k]` is the start of segment k), `.cut_times()`, and `.at(t)`.

## Per-frame effects hook

```python
def fx(t, i, g, u, p):   # t=output time, i=segment index, g=Seg, u=progress in segment
    p['zoom'] *= ...; p['cx'], p['cy'], p['rot']
    p['shake'] = (dx, dy)      # px
    p['blur']  = (bx, by)      # directional motion blur strength, px (whip transition)
    p['flash'] = 0..1          # white flash
    p['bright'] = 0..1         # exposure pop on hits
```
Proven patterns (used by formats.py): a zoom punch decaying over 0.18–0.28 s after each cut; whip blur from 0.07 s before to 0.1 s after each cut (strength 45–55, since stronger smears too many frames); a decaying sinusoidal shake on slams and reveals; a white flash on the reveal; a subtle beat pulse on static hook and tail shots.

## Grade

`make_grade(contrast, sat, warm, lift, vignette, gamma)` returns `f(img)`. Templates also wrap it: teal shadows and warm highlights (velocity), grain plus a desaturated freeze (POV). Keep saturation ≤1.25, because food gets radioactive fast.

## Text and overlays

- `text_layer(lines, font(name, px), fill, stroke, stroke_fill, shadow, box, box_pad, line_gap)` returns a PIL RGBA image. `lines` is a str, a list of str, or a list of runs: `[[('ganti ', {}), ('OAT', {'fill': YEL, 'box': (r,g,b), 'font': other})]]`.
- `emoji_layer('🤯', px)` renders Apple Color Emoji. Use it as a separate overlay, because emoji inside `text_layer` won't render.
- `Overlay(img, t0, t1, x, y, anim, out, anchor, wobble, rot, slide)` where `anim` ∈ pop|slam|rise|slide|fade|none, `out` ∈ fade|none, and `anchor` ∈ center|left|right. Set `ov.silent = True` to skip the pop SFX; in formats, only overlays with `pop=True` get one.
- `render(..., extra_frame=f(img, t))` is for frame-level extras: grain, a progress bar, desaturation.

## Audio toolkit (mono float64 @ 44.1 kHz)

Instruments: `kick, snare, clap, hat(open_), cowbell(pitch), bass808(freq, dur, glide_from, dist), pad_chord, pluck, bell`.
FX: `whoosh, riser, impact, pop, swish_ding`.
Processing: `place(buf, clip, t, gain)`, `sidechain(x, beat_times)`, `duck(x, regions)`, `reverb`, `lowpass/highpass/bandpass`, `limiter`.
Original sound: `src_audio_track(tl, load_src_audio(), T, gain)` varispeeds the source audio along the same time map, so sizzles follow the speed ramps.
Mixing: `write_wav`, `read_wav`.

Mix recipe (build.make_audio): drums ~0.55–0.7, music ~0.6–0.8, SFX ~0.7, natural sound ~0.7–0.9. Add light reverb, normalize to ×1.25–1.35 into `limiter`, and fade the last 0.1 s. This lands around -13 to -14 LUFS. Drop drums for 1–2 beats before the reveal (riser or tape-stop), then hit `impact` + `swish_ding` on the reveal.

## render()

`render(tl, out_path, wav_path, overlays, fx=None, grade=None, smooth_thresh=0.7, extra_frame=None)` returns the ffmpeg rc. It encodes x264 CRF 17 with AAC 256k and faststart. Source frames are cached as JPEG bytes and only one optical-flow pair is kept, so memory stays under ~1 GB.
