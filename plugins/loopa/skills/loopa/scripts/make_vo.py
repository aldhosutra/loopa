"""Build voice-over lines with Kokoro (Indonesian via espeak IPA), fit each into its time window,
get word timings with Whisper, write VO json for the video scripts.
usage: .ttsenv/bin/python make_vo.py SCRIPT.json OUTDIR"""
import sys, os, json, re, difflib
import numpy as np, soundfile as sf
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tts_id import synth
from faster_whisper import WhisperModel

spec = json.load(open(sys.argv[1])); out_dir = sys.argv[2]; os.makedirs(out_dir, exist_ok=True)
voice = spec['voice']; base = spec.get('speed', 1.1)
wm = WhisperModel('small', device='cpu', compute_type='int8')
SRK = 24000

def trim(a, thr=0.003):
    idx = np.where(np.abs(a) > thr)[0]
    if not len(idx): return a
    return a[max(0, idx[0] - 1800): idx[-1] + 2400]

def norm(w): return re.sub(r'[^a-z0-9]', '', w.lower())

lines = []
for k, ln in enumerate(spec['lines']):
    win = ln['end'] - ln['t']; sp = base
    for _ in range(6):
        a, ps = synth(ln['text'], voice, sp); a = trim(a)
        dur = len(a) / SRK
        if dur <= win or sp >= 1.3: break
        sp = min(1.3, sp * dur / win * 1.02)
    a = a / (np.abs(a).max() + 1e-9) * 0.9
    path = os.path.join(out_dir, f'line{k:02d}.wav'); sf.write(path, a, SRK)
    # word timings from whisper, mapped onto our own script words
    segs, _ = wm.transcribe(path, language='id', word_timestamps=True, beam_size=5)
    hw = [(w.word.strip(), w.start, w.end) for s in segs for w in s.words]
    words = ln['text'].split()
    times = [None] * len(words)
    sm = difflib.SequenceMatcher(None, [norm(w) for w in words], [norm(w[0]) for w in hw])
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'equal' or (op == 'replace' and i2 - i1 == j2 - j1):
            for d in range(i2 - i1): times[i1 + d] = (hw[j1 + d][1], hw[j1 + d][2])
    # interpolate missing words by character share
    total = dur; n = len(words)
    for i in range(n):
        if times[i] is None:
            prev_end = times[i - 1][1] if i and times[i - 1] else (0 if i == 0 else None)
            if prev_end is None:
                prev_end = sum(len(w) for w in words[:i]) / sum(len(w) for w in words) * total
            nxt = next((times[j][0] for j in range(i + 1, n) if times[j]), total)
            span = max(nxt - prev_end, .12); cnt = next((j for j in range(i + 1, n) if times[j]), n) - i
            times[i] = (prev_end, prev_end + span / cnt)
    lines.append({'t': ln['t'], 'wav': path, 'text': ln['text'], 'speed': round(sp, 2), 'dur': round(dur, 2),
                  'words': [[w, round(a_, 3), round(b_, 3)] for w, (a_, b_) in zip(words, times)],
                  'heard': ' '.join(w[0] for w in hw)})
    warn = '   !! line longer than its window: shorten it or anchor it later' if dur > win + .05 else ''
    print(f"[{ln['t']:5.2f}-{ln['end']:5.2f}] {dur:4.2f}s sp={sp:.2f} | {ln['text']}  ->  {' '.join(w[0] for w in hw)}{warn}")
json.dump({'lines': lines}, open(os.path.join(out_dir, 'vo.json'), 'w'), indent=1)
