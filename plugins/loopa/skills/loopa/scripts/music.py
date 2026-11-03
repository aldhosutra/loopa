"""Music-first loop beds. The music is composed as a CYCLE of N whole bars: it never "ends", it turns around.

Structure of every loop (what makes end->start feel like a song section, not an edit):
  * bar 0 = the DROP: full groove from the first downbeat (the video's hook lands on it),
  * optional mid BREAK: drums drop out for `brk` seconds before the reveal, then slam back,
  * last bar = BUILD: kick drops, snare roll accelerates (8ths -> 16ths), filter opens, harmony goes to the
    progression's last chord, so it resolves into bar 0's first chord on the replay,
  * TAIL-TO-FRONT: notes are only started inside the cycle, but they ring past its end; that ring-out is folded onto
    the start, so the waveform is exactly periodic and no crossfade is ever needed.
music(style, P, bpm, key=0, seed=0, brk_at=None, brk=0.0) -> (exactly periodic mono array, len = round(P*SR), beats)"""
import math
import numpy as np
from engine import *

STYLES = ('upbeat', 'lofi', 'phonk', 'ambient', 'cinematic', 'house')
DEFAULT_BPM = {'upbeat': 120, 'lofi': 92, 'phonk': 140, 'ambient': 80, 'cinematic': 90, 'house': 124}
TAIL = 4.0  # ring-out rendered past the cycle and folded onto its start

PROGS = [  # (chord tones in Hz before transposition, bass root); index 3 leads back to index 0
    [([174.6, 220.0, 261.6, 329.6], 43.65), ([196.0, 246.9, 293.7, 349.2], 49.0), ([164.8, 196.0, 246.9, 293.7], 41.2), ([220.0, 261.6, 329.6, 392.0], 55.0)],
    [([220.0, 261.6, 329.6, 392.0], 55.0), ([174.6, 220.0, 261.6, 329.6], 43.65), ([130.8, 164.8, 196.0, 246.9], 65.4), ([196.0, 246.9, 293.7, 349.2], 49.0)],
    [([146.8, 174.6, 220.0, 261.6], 73.4), ([196.0, 246.9, 293.7, 349.2], 49.0), ([130.8, 164.8, 196.0, 246.9], 65.4), ([110.0, 164.8, 196.0, 261.6], 55.0)],
]

def _rhodes(f, dur, amp=.08):
    m = int(dur * SR); t = np.arange(m) / SR
    x = np.sin(2*np.pi*f*t + .8*np.sin(2*np.pi*f*t)*np.exp(-t*4)) * np.exp(-t * 1.6) * (1 + .15 * np.sin(2*np.pi*4.5*t))
    return x * np.minimum(1, t / .005) * np.minimum(1, (dur - t) / .08).clip(0, 1) * amp

def fold(buf, Ps):
    """tail-to-front: everything that rings past the cycle end is laid over the cycle start -> exactly periodic"""
    out = buf[:Ps].copy(); tail = buf[Ps:]
    while len(tail):
        k = min(len(tail), Ps); out[:k] += tail[:k]; tail = tail[k:]
    return out

def circular_reverb(x, wet=.08):
    """reverb whose tail wraps around the cycle (convolve two periods, keep the second)"""
    Ps = len(x); y = reverb(np.concatenate([x, x]), wet)
    return y[Ps:2 * Ps]

def music(style, P, bpm=None, key=0, seed=0, brk_at=None, brk=0.0):
    bpm = bpm or DEFAULT_BPM[style]; B = 60 / bpm; kr = 2 ** (key / 12)
    r = np.random.default_rng(seed); prog = PROGS[seed % len(PROGS)]
    Ps = int(round(P * SR)); n = Ps + int(TAIL * SR); mus = np.zeros(n); dr = np.zeros(n)
    N = max(1, int(round(P / (4 * B)))); nb = 4 * N; beats = []
    chord_of = lambda bar: prog[3] if (bar == N - 1 and N > 1) else prog[bar % 4]   # last bar turns around to I
    in_break = lambda t: brk_at is not None and brk > 0 and brk_at - brk <= t < brk_at and brk_at < (N - 1) * 4 * B
    build_bar = lambda bi: N > 1 and bi // 4 == N - 1
    for bi in range(nb):
        t = bi * B; chord, root = chord_of(bi // 4); chord = [c * kr for c in chord]; root *= kr
        quiet = in_break(t); bld = build_bar(bi); pos = bi % 4
        # ---- harmony / melody (always on, so the cycle never thins out at the seam)
        if style == 'upbeat':
            if pos == 0: place(mus, pad_chord(chord, 4 * B, 2200, .1), t)
            arp = chord + [chord[1] * 2]; pat = [[0, 2, 4, 2], [0, 1, 2, 3], [4, 2, 1, 2]][seed % 3]
            for j, nt in enumerate(pat): place(mus, pluck(arp[nt] * 2, .3, .07), t + j * B / 4)
        elif style == 'house':
            if bi % 2 == 0:
                for c in chord: place(mus, pluck(c * 2, .25, .05), t + (B * .75 if seed % 2 else 0))
        elif style == 'lofi':
            if pos == 0:
                for f in chord + [chord[2] * 2]: place(mus, _rhodes(f, 4 * B), t + r.uniform(0, .02))
        elif style == 'phonk':
            scale = [1, 1.189, 1.335, 1.498, 1.782, 2]
            pat = [[0, -1, 2, -1, 3, -1, 2, 0, -1, 4, -1, 3, 2, -1, 1, -1], [0, 0, -1, 2, -1, 3, -1, 2, 4, -1, 3, -1, 2, 1, -1, 0]][seed % 2]
            for s16 in range(4):
                st = pat[(bi * 4 + s16) % 16]
                if st >= 0: place(mus, cowbell(.3, scale[st] * .75 * kr), t + s16 * B / 4, .5)
        elif style == 'ambient':
            if pos == 0: place(mus, pad_chord(chord, 4 * B + .5, 1200, .08), t)
            if r.random() < .45: place(mus, bell(r.choice(chord) * 2, 1.4, .05), t + r.choice([0, B / 2]))
        elif style == 'cinematic':
            if bi % 8 == 0 or (bi == 0):
                m = int(min(8, nb - bi) * B * SR); place(mus, np.sin(2*np.pi*root*np.arange(m)/SR) * env(m, .3, 4) * .3, t)
                place(mus, pad_chord(chord, min(8, nb - bi) * B, 900, .09), t)
            place(mus, pluck(chord[-1] * 2, .4, .04), t)
        # ---- rhythm section
        if quiet or style == 'ambient':
            if style == 'ambient' and pos == 0: beats.append(t)
            continue
        if bld:   # build bar: no kick on the back half, accelerating snare roll, rising gain -> resolves into bar 0
            if pos < 2:
                place(dr, kick(.35, 150, 45, .8, 1.3), t, .8); beats.append(t)
            sub = 2 if pos < 2 else 4
            for s_ in range(sub):
                g = .18 + .42 * ((pos * sub + s_) / (4 * sub))
                place(dr, lowpass(snare(), 5000 if style == 'lofi' else 8000), t + s_ * B / sub, g)
            if style in ('phonk', 'upbeat', 'house') and pos < 2: place(mus, bass808(root, B * .9, dist=2.2), t, .5)
            continue
        if style == 'upbeat':
            beats.append(t); place(dr, kick(), t, .95)
            if bi % 2: place(dr, clap(), t, .8)
            place(dr, hat(open_=True), t + B / 2, .45); place(dr, hat(), t + B / 4, .3); place(dr, hat(), t + 3 * B / 4, .25)
            place(mus, bass808(root * 2, B * .9, dist=1.6), t, .5)
        elif style == 'house':
            beats.append(t); place(dr, kick(.35, 150, 45, 1, 1.4), t, .95)
            if bi % 2: place(dr, clap(), t, .6)
            place(dr, hat(open_=True), t + B / 2, .5)
            place(mus, bass808(root * 2, B * .4, dist=2.0), t + B / 2, .55)
        elif style == 'lofi':
            sw = B / 2 * 1.12
            if bi % 2 == 0: beats.append(t); place(dr, kick(.4, 110, 42, .3, 1.0), t, .9); place(mus, bass808(root, B * 1.8, dist=2.4), t, .45)
            if pos == 3: place(dr, kick(.4, 110, 42, .3, 1.0), t + sw, .55)
            if bi % 2 == 1: place(dr, lowpass(snare(), 6000), t, .7)
            place(dr, lowpass(hat(), 9000), t, .3); place(dr, lowpass(hat(), 9000), t + sw, .22)
        elif style == 'phonk':
            if bi % 2 == 0: beats.append(t)
            place(dr, kick(.35, 180, 48, 1.2, 2.0), t if bi % 2 == 0 else t + B * .75, .95)
            if bi % 2: place(dr, clap(), t, .7)
            k3 = 3 if pos == 3 else 2
            for s_ in range(k3): place(dr, hat(), t + s_ * B / k3, .28)
            if bi % 2 == 0: place(mus, bass808(root, B * 1.9, glide_from=root * 1.5 if (bi // 4) % 2 else None, dist=3.5), t, .7)
        elif style == 'cinematic':
            if pos == 0: beats.append(t); place(dr, lowpass(kick(.9, 90, 32, .5, 1.2), 400) * 1.2, t, .9)
            if pos == 2: place(dr, lowpass(kick(.5, 120, 50, .3, 1), 600), t, .5)
    out = sidechain(mus, beats, .45 if style in ('upbeat', 'house', 'phonk') else .2) * .85 + dr * .7
    if style == 'lofi':
        cr = np.zeros(n); idx = r.integers(0, n, int(P * 25)); cr[idx] = r.uniform(-.6, .6, len(idx)); out += highpass(cr, 2000) * .1
        out = lowpass(out, 9000)
    if N > 1:  # filter opens through the build bar (dark -> full) and lands fully open on bar 0
        a, b = int((N - 1) * 4 * B * SR), Ps
        w = np.linspace(0, 1, b - a) ** 1.5; dark = lowpass(out[a:b], 900)
        out[a:b] = dark * (1 - w) + out[a:b] * w
    return fold(out, Ps), beats

def tape_stop(x, t0, t1):
    a0, a1 = int(t0 * SR), int(t1 * SR); seg = x[a0:a1].copy(); L = a1 - a0
    if L <= 0: return x
    pos = np.clip(np.cumsum(np.linspace(1, 0, L) ** .7), 0, L - 1)
    x[a0:a1] = np.interp(pos, np.arange(L), seg) * np.linspace(1, .2, L); x[a1 - int(.1 * SR):a1] = 0
    return x
