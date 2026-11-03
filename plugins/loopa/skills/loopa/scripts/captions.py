"""Voice-over placement + word-highlight captions.
VO json: {"lines": [{"t": start_sec, "wav": path, "text": "...", "words": [[word, t0, t1], ...]}]}
word times are relative to the line start."""
import numpy as np
from engine import *

def place_vo(VO, L):
    out = np.zeros(L); regions = []
    for ln in VO['lines']:
        x = read_wav(ln['wav'])
        place(out, x, ln['t'])
        regions.append((ln['t'], ln['t'] + len(x) / SR))
    return out, regions

def chunks(words, maxw=3, maxc=16):
    out, cur = [], []
    for w in words:
        if cur and (len(cur) >= maxw or sum(len(c[0]) for c in cur) + len(w[0]) > maxc):
            out.append(cur); cur = []
        cur.append(w)
        if w[0].endswith(('.', ',', '?', '!')): out.append(cur); cur = []
    if cur: out.append(cur)
    return out

def word_captions(VO, y=.70, size=82, hi=(255, 214, 10), fnt='Poppins-Black.ttf'):
    f = font(fnt, size); ovs = []
    for ln in VO['lines']:
        t0 = ln['t']
        for ch in chunks(ln['words']):
            for k, (w, a, b) in enumerate(ch):
                runs = []
                for j, (w2, _, _) in enumerate(ch):
                    txt = w2.upper().strip(',.') + (' ' if j < len(ch) - 1 else '')
                    runs.append((txt, {'fill': hi if j == k else (255, 255, 255)}))
                img = text_layer([runs], f, stroke=9, stroke_fill=(0, 0, 0), shadow=10)
                end = ch[k + 1][1] if k + 1 < len(ch) else b + .12
                ov = Overlay(img, t0 + a, t0 + end, y=y, anim='pop' if k == 0 else 'none', out='none')
                ov.silent = True
                ovs.append(ov)
    # never let two caption states overlap: each one ends when the next begins
    ovs.sort(key=lambda o: o.t0)
    for a, b in zip(ovs, ovs[1:]):
        a.t1 = min(a.t1, b.t0 - 1e-3)
    return [o for o in ovs if o.t1 > o.t0]
