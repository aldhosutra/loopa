# Anti AI-slop

Audiences and platforms punish content that feels generated: low effort, published at volume, sameness. The penalty is about perceived effort and authenticity more than detection. One industry study (Ipsos/Syracuse, 2026) found only 13% of viewers were confident an ad was AI-made, yet human-made ads performed 14–17% better. YouTube made "AI slop" a 2026 priority, and Instagram (Apr 2026) stops recommending accounts that post mostly unoriginal content. Real footage of real hands is this skill's advantage. The edit, copy, and voice must not throw that away.

Run this checklist on **every plan before rendering** and on **every render during QC**. Fix the failures, don't just note them.

## 1. Copy and narration (Indonesian)

**Cut these on sight**, because they read as template or AI copy:
- Openers: "Siapa sangka…", "Tahukah kamu?", "Yuk simak!", "Inilah…", "Tanpa basa-basi…", "Halo guys, kali ini…", "Rahasia …", "Kalian wajib coba!!", "Dijamin…"
- Empty food adjectives: "lezat dan bergizi", "sehat dan lezat", "praktis dan mudah", "menggugah selera", "nikmat tiada tara", "bikin nagih", "auto ketagihan", "level up", "game changer", "comfort food versi sehat"
- Structures: triads ("murah, mudah, sehat"), "Bukan X, tapi Y" over and over, a rhetorical question answered right away, every line ending in "!", stacked hype words
- Formal register on casual platforms: "Anda", "mari kita", "berikut adalah", "sangat"
- Narrating what's on screen: "di sini saya memasukkan kol". The footage already shows it. Say the why, the feeling, or the twist instead.
- Health or nutrition claims you can't back up ("rendah kalori", "70% lebih sehat"), invented prices, invented cook times. The timer format shows *recording* time, so never claim it's cooking time.
- Fake testimony presented as fact ("keluargaku langsung ketagihan"). Fictional POV framing like "POV:" and "tanggal tua" is a recognized device and fine. Tell the user which videos use a fictional framing so they can swap in their real story.

**Do this instead:**
- Be concrete and specific to the footage: name the ingredient, the order ("oatnya masuk paling akhir"), a texture you can see, a sound you can hear.
- Write the way a person talks: short, uneven sentence lengths, particles (deh, sih, kok, ya), one consistent pronoun (aku or gue, not both).
- Include one honest beat: doubt, a small admission, a real opinion ("jujur awalnya ragu").
- Keep it light. A line every 2–3 s is plenty, and leave the hit moments unspoken.
- If the `humanizer` skill is available, run narration and on-screen copy through it once.
- The best anti-slop voice is the creator's own. Offer the VO lines as a script the user can record, with Kokoro as the fallback.

## 2. On-screen text and design

- **Emoji: at most one per video**, and only where it adds meaning. Never 🤯😭👇🔥✨ on every line.
- "POV:" only when the video really is a point-of-view scene. Don't run it on a third of the batch.
- Rotate the **type kit** across a batch (bold, native, editorial, minimal, rounded, grotesk). Never give two consecutive videos the same kit and grade.
- One reading at a time: a headline or captions or karaoke, never all three competing. In dubbed versions, story captions are dropped automatically.
- No glow, neon outline, gradient text, or random rotation on everything. Small deliberate tilts (−2° to −4°) only on slam words.
- Text matches the cut: it changes on the beat or cut, not at random times.

## 3. Edit and motion

The classic slop look is the same effect on every cut.
- **Motivated effects only.** A zoom punch where something lands, whip blur where motion already exists, shake only on the one or two biggest hits. Formats flag effects per segment (`fx={'punch'}` etc.). Don't add them to every segment.
- **Vary cut lengths.** Mix 1-, 2-, and 3-beat shots. A metronome of identical durations feels machine-made.
- Slow-mo on real moments of interest (a drop, a pour, a crack), not on everything.
- Don't stack effects: no shake + flash + punch + whoosh + pop on one cut.
- Keep the grade believable: saturation ≤ 1.25, and no HDR halos or crushed orange skin. Food should look edible, not radioactive.
- Avoid a "fake camera" layer (constant handheld wobble added in post).

## 4. Audio

- SFX budget: whooshes only on whip cuts, pops only on headline text (`pop=True`), and impacts only on real hits and the reveal. Avoid slot-machine sound.
- Music bed: vary style, key, and seed per video (the checker enforces this). Loops must not end on a final chord.
- Natural sound is the authenticity layer, so keep the sizzle audible under the music. ASMR leans on it.
- TTS: keep lines short, use punctuation for rhythm, keep speed ≤ ~1.25, and check what Whisper heard. If a line sounds robotic, rewrite it shorter.
- Recommend swapping in a platform trending sound for non-dubbed uploads.

## 5. Batch-level sameness (volume mode)

Posting many videos from one footage is fine. Posting many *near-identical* videos is what gets an account labeled unoriginal.
- Every video must differ in its **first 2 seconds** (opening shot + hook text), **format**, **copy**, and **music bed**. `build.py --check` enforces format+angle, opening shot, and music uniqueness.
- Variants (same format, different hook or voice) are allowed only when marked with `variant_of`. Tell the user to post them days apart or as trial/test posts.
- Spread formats and kits across the posting order (don't post three velocity edits in a row).

## QC gate (copy into the final report)

- [ ] No banned phrases or structures, no unverifiable claims, fictional framings disclosed
- [ ] ≤ 1 emoji per video; one reading at a time
- [ ] Effects motivated, not uniform; cut lengths varied
- [ ] Grade believable; text readable at phone size
- [ ] SFX budget respected; natural sound audible; loudness about -14 LUFS
- [ ] `build.py --check` OK; variants marked
