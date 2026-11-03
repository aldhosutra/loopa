# Indonesian dubbing with Kokoro

Kokoro-82M has no official Indonesian. Its languages are en, es, fr, hi, it, ja, pt-BR, and zh. It works anyway because Kokoro's acoustic model consumes IPA phonemes. `tts_id.py` gets Indonesian IPA from `espeak-ng -v id` and feeds it straight to the model, skipping Kokoro's G2P. Tell the user this up front: it's a workaround, and the result has a slight foreign accent.

## Setup (once)

```bash
bash scripts/setup_tts.sh ~/.loopa/tts      # or: install.sh --with-tts   (auto-detected; plan "tts_python" overrides)
```
This needs `espeak-ng` (`brew install espeak-ng`), plus system-wide `torch`, `soundfile`, and `faster-whisper`. It installs only `kokoro` and `misaki` with `--no-deps`, plus `loguru` and `addict`. `tts_id.py` loads `kokoro.model` without running `kokoro/__init__`, which would pull in spacy and the whole English stack. Model and voices download from the HF hub `hexgrad/Kokoro-82M` on first use (~330 MB plus ~0.5 MB per voice). Run TTS work only when no render is running.

## Choosing a voice

`ENV/bin/python scripts/voice_test.py <dir> "kalimat uji ..."` synthesizes each voice and scores how well Whisper (language=id) recovers the words. Measured results:

| voice | score | note |
|---|---|---|
| ef_dora (es, F) | 0.93 | clearest; good for storytime |
| em_alex (es, M) | 0.93 | clear; good for energetic recipe narration |
| pf_dora (pt-BR, F) | 0.93 | clear |
| af_heart (en, F) | 0.81 | more English accent |
| if_sara / im_nicola (it) | 0.70 | weaker |

"tanpa" is often heard as "tampa". That matches natural nasal assimilation and is fine. Words that stand alone, like "oat!", are hard to recognize without context. Pair them with big on-screen text.

## Writing the lines (in plan.json)

Add `"vo": {"voice": "em_alex", "speed": 1.1, "lines": [...]}` to a video. Mark it `"variant_of": "<id>"` when the same format already exists without voice. The output gets a `_DUB` suffix.
- Lines are strings or `{"text": "...", "at": <anchor>}`. An anchor is a moment id (the line starts when that moment's segment starts), `hook`, `reveal`, `end`, or seconds. **Anchor lines that name what's on screen.** Without anchors the voice drifts off the picture ("oat disangrai" over the cabbage). Unanchored lines share the remaining time in proportion to their length.
- One short line per window, conversational and in the creator's voice. Plan about 2.5–3 words per second. Leave the reveal hit and the hook slam free of speech where you can.
- If `make_vo` reports speed ≥ 1.3 for a line, it's too long for its window. Shorten the text. At 1.4 Whisper starts mishearing ("KUMBU CAT CHAPTER" for "bumbu, kecap").

## Generate, check, render

`build.py` does everything: it computes the windows, runs `make_vo.py` with `tts_python` (synthesize, fit, Whisper word timings), and renders with ducking and karaoke captions. Read the `[t0-t1] … -> heard` lines it prints. If a first sound is missing ("Asingnya" for "Nasinya"), the trim is cutting soft onsets. The trim threshold is 0.003 with a 75 ms pre-roll for that reason, so don't raise it. Word timings come from Whisper word timestamps mapped back onto the script words, and unmatched words are interpolated.

In the dubbed render, the music and natural sound duck under speech, the story captions are dropped (kit captions are tagged `role=caption`) because the voice now carries them, punchline graphics stay, and karaoke captions are added (`captions.word_captions`). Those show the current 1–3 word chunk with the spoken word in yellow. Caption states never overlap: each one ends when the next starts. Without that, chunk boundaries showed two captions on top of each other ("NA:GANTI KU").

QC the dubbed render with a 4 fps grid over the speech-heavy part, looking for overlapping captions, and check loudness.
