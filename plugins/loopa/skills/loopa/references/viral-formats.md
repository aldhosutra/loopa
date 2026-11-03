# Viral format library

**Length = natural length per format, not a fixed number.** 2026 roundups (vendor blogs, directional): 7–15 s is the "viral sweet spot" with the highest completion (Reels 60–80%); 15–30 s is the strongest TikTok engagement band (Socialinsider, ~6M videos: 15–30 s ≈ 6%); Shorts completion peaks around 20–25 s; longer videos win raw views only for value content. One academic study found length explains little, and hook + retention dominate. Defaults (`formats.NATURAL`): quiz 9, loops/transformation/split 10, montage/timelapse 11, count 12, velocity 13, compilation 14, result-first/ASMR 15, myth-fact 16, POV 17, listicle 18, kinetic story 20. Ceiling `max_s` 30. `finish()` re-times uniformly (±35%) to the natural or `target_s` length, then the loop bridge closes it. Sources: [bytecap](https://www.bytecap.io/blog/optimal-short-form-video-length-retention-analysis), [socialinsider](https://www.socialinsider.io/blog/how-long-are-tiktok-videos/), [joyspace](https://joyspace.ai/ideal-video-length-social-platform-2026), [virvid](https://virvid.ai/blog/best-shorts-length-retention-2026), [arXiv finfluencer study](https://arxiv.org/pdf/2607.05203).

Formats that recur in 2026 short-form roundups ([hookclone](https://www.hookclone.com/blog/trending-tiktok-formats-2026), [flowcree](https://www.flowcree.com/en/blog/viral-video-formats), [teleprompter](https://www.teleprompter.com/blog/trending-youtube-shorts), [opus.pro](https://www.opus.pro/blog/editing-aesthetics-dominating-short-form-2026)). These are mostly vendor blogs, so treat them as craft guidance, not measured data. Each entry maps to a builder in `scripts/formats.py` (the name in brackets) and lists its `copy` keys and useful `opt` keys.

Shared `opt` keys: `kit` (bold|native|editorial|minimal|rounded|grotesk), `music` (upbeat|lofi|phonk|ambient|cinematic|house), `bpm`, `grade` (warm|film|clean|moody|pop|teal), `hook_moment`, `rotate`. Shared plan keys: `key` (−5..5 semitones), `seed`.

## Choosing formats for a footage

| Footage has… | Strong formats |
|---|---|
| a clear finished result (plating, final product) | result_first, transformation, quiz, ingredient_count |
| several distinct "drop/pour/crack" hits | velocity, compilation, satisfying_loop, montage |
| a surprising twist (substitute ingredient, unusual tool) | velocity (curiosity), quiz, myth_fact, pov_story |
| a long continuous process | timelapse_timer, split_compare, asmr |
| good natural sound (sizzle, crunch) | asmr, satisfying_loop |
| an arguable claim or tip | listicle, myth_fact, kinetic_story |

Formats that need footage this skill can't invent (a talking head, a reaction, a duet/stitch partner, day-in-the-life across locations) only work when the user supplies that footage. Don't fake them with text.

## Looping (every video loops, music-first)

Loops make the end flow back into the start, so viewers rewatch without noticing. A seamless loop costs nothing, so **every format loops**, and `formats.finish()` enforces it. The approach is **music-first**: the soundtrack is a musical cycle and the video is cut to it, not the other way round. Crossfading the end of a linear soundtrack into its start (an earlier version of this skill) sounds "cut then faded" on TikTok, so don't do that.

1. **The video is N whole bars.** Formats are built in beats, `fit_to_target` re-times the edit (±35%) to the natural length, and the loop bridge pads it to whole bars, snapped to 16-frame multiples (whole AAC blocks at 48 kHz, so no encoder padding at the seam).
2. **The music is a cycle** (`music.py`). Bar 0 is the **drop**, with full groove on the first downbeat, where the hook lands. The last bar is the **build**: the kick drops out, a snare roll accelerates from 8ths to 16ths, the filter opens, and the harmony moves to the progression's last chord so it resolves into bar 0 on replay. An optional mid **break** clears the drums before the reveal.
3. **Tail-to-front** (the game-audio standard): notes, SFX, voice, and reverb only start inside the cycle, but they ring past its end, and that ring-out is laid over the start (`music.fold`, `music.circular_reverb`). The waveform is exactly periodic, with **no crossfade and no fade**. On replay the sound simply keeps going: build → drop.
4. **Picture**: a bridge plays the footage just *before* the opening shot (with the opening's camera framing), so the last frame runs straight into the first. The footage's own sound is continuous for the same reason. With no usable lead-in (a scene cut right before the moment), the bridge becomes a boomerang. Every moment must sit inside one shot (`--check` fails otherwise).
5. **Loudness** is set with one linear gain plus a memoryless soft clip (`engine.normalize_periodic`), never a time-varying normalizer, which would make the start and end gain differ.
6. **Voice** ends ≥ 0.4 s before the loop point, so the build → drop is clean.
7. **Text**: end cards run to the last frame, and the hook text is on screen from the first frame. They swap on the drop, which reads like a re-hook.
8. **Narrative loop (copy)**: when it fits, the last line leads into the first ("…makanya nasinya kuganti" → "OAT."). Never end with sign-offs ("follow for more"), because they close the loop.

QC: `scripts/loop_check.sh video.mp4 seam.jpg` scores the video seam and the audio seam. To *watch* a loop, run `scripts/loop_preview.sh video.mp4 3`, which writes the video 3× back-to-back into one file. Player repeat modes (VLC etc.) reopen the file and add a hitch to every video. The final check is a private/draft upload, since platforms re-encode.

Using the user's own song instead of synthesized music: find a loopable section with [PyMusicLooper](https://github.com/arkrow/PyMusicLooper), make the video exactly that many bars, and lay the loop region under it. Mind the licensing.
Sources: [MakeUseOf: seamless game-music loops (tail-to-front)](https://www.makeuseof.com/how-to-create-music-loop-video-games/), [Hackernoon: seamless game loop with FFmpeg](https://hackernoon.com/how-to-turn-an-ai-generated-track-into-a-seamless-game-loop-with-ffmpeg-godot-unity-and-web-audio), [VI-Control: looping VGM](https://vi-control.net/community/threads/seamless-looping-videogame-music.64394/), [OC ReMix: seamless loops](https://ocremix.org/community/topic/41570-creating-seamless-loops-for-video-games/), [violetrecording loop maker (equal-power, 20–50 ms)](https://violetrecording.com/tools/loop-maker/), [Audjust: perfect loop for TikTok](https://www.audjust.com/help/create-perfect-loop-for-tiktok).

## Formats

### 1. Result-first recipe [result_first]
Hook: the finished result plus a bold claim box. Then numbered step chips on the beat, a build, the reveal, and a CTA tail that loops into the hook. 11–15 s.
copy: `hook`, `reveal_big`, `reveal_sub?`, `cta`, `labels?{moment:label}`. opt: `hook_moment`, `max_steps`.

### 2. POV storytime [pov_story]
"POV: …" relatable setup, the story told in 4–6 captions, a freeze-frame with a red-circle callout on the twist, a lo-fi tape-stop into a drop on the reveal, and a comment-keyword CTA. 15–17 s. Use "POV" sparingly across a batch.
copy: `lines[5..6]` (0 = hook, 1 = right before the freeze), `freeze_word`, `punch`, `cta`. opt: `hook_moment`, `hero_moment` (freeze target).

### 3. Velocity / speed-ramp [velocity]
Every shot rushes in and snaps to slow-mo on the hit. An ingredient list stacks up, the hook is a curiosity denial ("ini bukan nasi."), and the payoff is the reveal. Phonk. 13–15 s. Uniform punch+whip is this genre's grammar, which makes it the one exception to the "motivated effects" rule.
copy: `hook_small`, `hook_big`, `reveal_small`, `reveal_big`, `reveal_sub?`, `cta`.

### 4. Satisfying loop [satisfying_loop]
A story-free sequence of satisfying actions (default 5, one bar each), slow-mo, ~10 s, seamless loop. Choose actions whose motion repeats well (pours, drops, tosses), and give two loop videos different moment sets. An optional single setup line.
copy: `line?`. opt: `moments` (≈5 ids), `count`, `beats_each`, `rate`, `rotate`.

### 5. Transformation cut [transformation]
The before state holds while tension builds. The cut lands one beat before the drop to the after, then a top/bottom split SEBELUM/SESUDAH, then a loop. 8–12 s.
copy: `before`, `after`, `label_before?`, `label_after?`. opt: `before_moment`, `after_moment`.

### 6. Numbered listicle [listicle]
"3 hal soal …" title hook, one item per 2–3 s with a big number over matching b-roll, CTA. 10–20 s. Items must be true of the footage.
copy: `title`, `items[3..5]`, `cta`. opt: `item_moments`.

### 7. Myth vs fact [myth_fact]
A desaturated MITOS card, then FAKTA flips it over proof shots, then a conclusion or debate CTA. 12–15 s.
copy: `myth`, `fact`, `proof[]`, `cta`. opt: `myth_moment`, `proof_moments`.

### 8. Guess what [quiz]
An ambiguous extreme close-up with "tebak, ini apa?", a 3-2-1 countdown on the beat, a zoom-out answer, a fast proof recap, and a comment bait. 7–10 s, so it's highly rewatchable.
copy: `question`, `answer`, `answer_sub?`, `cta`. opt: `close_moment`.

### 9. ASMR / sound-first [asmr]
Long takes, slow-mo hits without shake, tiny lowercase labels at the bottom, a near-silent bed, and natural sound forward. 14–18 s.
copy: `line?`, `labels` (false to hide, or {moment:label}). opt: `moments`.

### 10. Montage to music [montage]
10–15 one-beat cuts ordered by vibe, the hero clip on the drop, one framing line. 8–12 s.
copy: `line?`, `end_line?`. opt: `cuts`, `rotate`.

### 11. Timelapse + timer [timelapse_timer]
The whole process in order, compressed, with a running counter of **footage time** (honest: recording time, not cooking time), then the result. 9–12 s.
copy: `hook`, `end_line`.

### 12. Ingredient / step count [ingredient_count]
A big counter ticks 1..N on each hit with the name. The hook promises the number ("*7 langkah*"). The number must match the footage. 10–12 s.
copy: `hook`, `end_line`, `labels?`. opt: `hook_moment`, `max_steps`.

### 13. Ranked compilation [compilation]
"5 momen paling satisfying" counts down #5→#1 with slow-mo. It can mix several footage files (moments with different `src`). It's the natural format for recycling many clips into one. 12–16 s.
copy: `title`, `items[]` (in display order, #N first), `cta?`. opt: `moments` (same order as items).

### 14. Kinetic text story [kinetic_story]
The text carries a micro-story (6–9 short lines changing on the bar). Footage is b-roll on the beat, and the result is the punchline. 15–20 s. Fictional framings ("tanggal tua") must be disclosed to the user.
copy: `lines[]`. opt: `beats_per_line`, `rotate`.

### 15. Split-screen process vs result [split_compare]
The whole video is split top/bottom, with steps on top and the result on the bottom, then a full-frame payoff. 8–10 s.
copy: `top`, `bottom`, `end_line?`. opt: `rotate`, `max_steps`.

## Multiplying one footage (volume mode)

For a new channel, quantity matters. One footage can yield 15–25 shorts without becoming duplicate content when each video differs on these axes:

| axis | options |
|---|---|
| format | the 15 above |
| angle / POV | diet, budget/anak kos, bahan sisa, edukasi, mitos, curiosity, debat, ASMR/aesthetic, speedrun, proses, one-pan… |
| hook | opening moment (`hook_moment`/`rotate`) + hook text |
| narration | none, caption story, voice-over (male/female voice), karaoke |
| look | type kit × grade |
| sound | music style × key × seed, or natural-sound-first |

Rules (enforced by `build.py --check`): unique format+angle, unique opening shot per format and each opening shot used at most twice, unique music bed, and same-format near-duplicates only as declared `variant_of`. Then add dubbed variants and hook variants of the strongest videos last.

A practical recipe for 1 footage → ~18 videos: 15 formats × 1 angle each, plus 2–3 dubbed variants of the strongest (result_first, pov_story), plus 1 extra satisfying loop per standout action.
