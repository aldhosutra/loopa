"""Format library. Each format turns (moments, copy, options) into a renderable spec.
A format decides structure, pacing, which moments to use and how; the plan supplies copy, angle, kit, music.

build(video_cfg, M) -> dict(tl, overlays, fx, grade, extra, audio, loop)
See references/viral-formats.md for what each format is for and its copy keys."""
import math, numpy as np, cv2
from PIL import Image, ImageDraw
from engine import *
from kits import KITS, F
from music import DEFAULT_BPM
from engine import _cam as engine_cam

# ------------------------------------------------------------------ moments
KINDS = ('before', 'action', 'process', 'result', 'reveal', 'macro')
class Moments:
    """moments.json: {"footage": {"c1": "/abs.mov" | {"path", "cuts": [s...], "crop": [cx, cy]}},
    "moments": [{"id","src","a","b","hit","kind","label","focus","lead_in"?}], "process_order": [ids...]}
    kinds: before | action | process | result | reveal | macro. lead_in defaults to the time since the last scene cut."""
    def __init__(s, data):
        s.footage, s.cuts = {}, {}
        for k, v in data.get('footage', {}).items():
            if isinstance(v, dict):
                s.footage[k] = v['path']; s.cuts[k] = sorted(v.get('cuts', []))
                if v.get('crop'): CROP[v['path']] = tuple(v['crop'])
            else: s.footage[k] = v
        s.list = [m for m in data['moments'] if m.get('kind') in KINDS]  # drafts may hold 'skip' / 'todo' shots
        s.by = {m['id']: m for m in s.list}
        s.order = [i for i in data.get('process_order', [m['id'] for m in s.list if m['kind'] in ('action', 'process')]) if i in s.by]
    def path(s, m): return s.footage.get(m.get('src', 'main')) or SRC
    def lead(s, m):
        if 'lead_in' in m: return m['lead_in']
        cuts = [c for c in s.cuts.get(m.get('src', 'main'), []) if c <= m['a'] + 1e-3]
        return max(0.0, m['a'] - (cuts[-1] if cuts else 0.0))
    def get(s, i): return s.by[i]
    def kind(s, *kinds): return [m for m in s.list if m['kind'] in kinds]
    def steps(s, kinds=('action',)): return [s.by[i] for i in s.order if s.by[i]['kind'] in kinds]
    def last_process(s):
        p = [s.by[i] for i in s.order if s.by[i]['kind'] == 'process']
        return p[-1] if p else s.first('process')
    def first(s, *kinds):
        k = s.kind(*kinds); return k[0] if k else None

_PROFILES = {
    'velocity': [(0, 3.6), (.3, 3.0), (.45, .28), (.85, .3), (1, 1.4)],
    'slowhit': [(0, 1.8), (.35, .4), (.75, .4), (1, 1.3)],
    'snap': [(0, 2.6), (.4, .45), (1, .8)],
}

def seg(M, m, dur, mode='normal', cam=None, tag=None, fx=(), rate=1.0, span=None):
    """Make a Seg from a moment. modes: normal | span | velocity | slowhit | snap | slow | freeze"""
    src = M.path(m); a, b = m['a'], m['b']; hit = m.get('hit', (a + b) / 2)
    fxc, fyc = m.get('focus', [.5, .5])
    c = dict(zoom0=1.15, zoom1=1.06, cx0=fxc, cx1=fxc, cy0=fyc, cy1=fyc)
    if cam: c.update(cam)
    if mode in _PROFILES:
        prof = _PROFILES[mode]; S = min(b - a, span or {'velocity': 2.6, 'slowhit': 2.4, 'snap': 2.2}[mode])
        f = Seg(0, 1, 1, speed=prof).src_time(.5)
        st = min(max(hit - f * S, a), b - S)
        g = Seg(st, st + S, dur, speed=prof, cam=c, tag=tag, src=src)
    elif mode == 'span':
        st = a if span is None else span; g = Seg(st, min(b, st + dur * rate), dur, cam=c, tag=tag, src=src)
    elif mode == 'slow':
        S = min(b - a, dur * rate * .5); st = min(max(hit - S / 2, a), b - S); g = Seg(st, st + S, dur, cam=c, tag=tag, src=src)
    elif mode == 'freeze':
        g = Seg(hit, hit + .01, dur, cam=c, tag=tag, src=src)
    else:
        g = Seg(a, b, dur, cam=c, tag=tag, src=src)
    g.fx = set(fx); g.moment = m['id']; g.m_a = a; g.m_lead = M.lead(m)
    return g

def hit_out(g, m):
    """output time (within the segment, 0..dur) at which the moment's hit happens"""
    hit = m.get('hit', (m['a'] + m['b']) / 2); us = np.linspace(0, 1, 200)
    st = g.src_time(us); return float(us[np.argmin(np.abs(st - hit))] * g.dur)

def rot(lst, opt):
    """opt['rotate']=n starts a pool at a different moment -> different opening shot per video"""
    n = opt.get('rotate', 0) % max(1, len(lst)); return lst[n:] + lst[:n]

def ov(img, t0, t1, y=.25, anim='pop', x=.5, pop=False, **kw):
    role = getattr(img, 'info', {}).get('role') if isinstance(img, Image.Image) else None
    o = Overlay(img, t0, t1, x=x, y=y, anim=anim, **kw); o.pop = pop; o.role = role; return o

def need(copy, *keys):
    miss = [k for k in keys if k not in copy]
    if miss: raise SystemExit(f'copy is missing keys {miss}')

def circle_img(w=900, h=700, color=(255, 40, 40, 255)):
    im = Image.new('RGBA', (w, h), (0, 0, 0, 0)); d = ImageDraw.Draw(im); pts = []
    for a in np.linspace(0.15, 2 * np.pi + .5, 90):
        r = 1 + .04 * np.sin(a * 3); pts.append((w / 2 + (w / 2 - 50) * r * np.cos(a), h / 2 + (h / 2 - 50) * r * np.sin(a)))
    d.line(pts, fill=color, width=22, joint='curve'); return im

# ------------------------------------------------------------------ grades
GRADES = {
    'warm':  dict(contrast=1.14, sat=1.2, warm=.045, vignette=.4),
    'film':  dict(contrast=1.06, sat=1.1, warm=.06, lift=.045, vignette=.45, gamma=1.0),
    'clean': dict(contrast=1.08, sat=1.12, warm=.02, vignette=.25),
    'moody': dict(contrast=1.2, sat=1.05, warm=.0, lift=.0, vignette=.6, gamma=1.04),
    'pop':   dict(contrast=1.16, sat=1.25, warm=.03, vignette=.3),
}
def make_grade_named(name):
    if name == 'teal':
        base = make_grade(contrast=1.2, sat=1.18, warm=.02, lift=.0, vignette=.55, gamma=1.02)
        T_, W_ = np.array([14, 6, -10], np.float32), np.array([-14, 2, 16], np.float32)
        def g(img):
            im = base(img).astype(np.float32); l = im.mean(2, keepdims=True) / 255
            im += (1 - l) ** 2 * T_; im += l ** 2 * W_; return np.clip(im, 0, 255).astype(np.uint8)
        return g
    return make_grade(**GRADES[name])

_GRAIN = None
def grain_extra(strength=7):
    global _GRAIN
    if _GRAIN is None: _GRAIN = (np.random.default_rng(3).standard_normal((4, H // 2, W // 2))).astype(np.float32)
    def f(img, t):
        g = cv2.resize(_GRAIN[int(t * 24) % 4] * strength, (W, H), interpolation=cv2.INTER_NEAREST)
        return np.clip(img.astype(np.float32) + g[..., None], 0, 255).astype(np.uint8)
    return f

# ------------------------------------------------------------------ fx
def make_fx(tl, hits=(), reveal=None, freeze=None):
    """Per-seg flags in g.fx: punch (zoom punch at its start), whip (blur across its start cut), pulse (beat pulse).
    hits: [(t, strength)] -> shake + exposure pop. Only flagged cuts get effects (anti-slop: motivated, not uniform)."""
    S = tl.starts; B = getattr(tl, 'B', .5)
    def fx(t, i, g, u, p):
        for k, gg in enumerate(tl.segs):
            if k == 0: continue
            dt = t - S[k]
            if 'punch' in gg.fx and 0 <= dt < .24: p['zoom'] *= 1 + .085 * (1 - ease_out(dt / .24))
            if 'whip' in gg.fx and -0.06 <= dt < .09: p['blur'] = (0, 48 * (1 - abs(dt) / .09)) if k % 2 else (48 * (1 - abs(dt) / .09), 0)
        for ht, s_ in hits:
            dt = t - ht
            if 0 <= dt < .14: p['bright'] = max(p['bright'], .3 * s_ * (1 - dt / .14))
            if 0 <= dt < .3:
                k_ = (1 - dt / .3) ** 2 * s_; p['shake'] = (20 * k_ * np.sin(dt * 100), 15 * k_ * np.cos(dt * 80))
        if reveal is not None and 0 <= t - reveal < .25: p['flash'] = .8 * (1 - (t - reveal) / .25) ** 2
        if freeze is not None and 0 <= t - freeze < .15: p['flash'] = .5 * (1 - (t - freeze) / .15)
        if 'pulse' in g.fx: p['zoom'] *= 1 + .018 * (1 - ease_out(((t % B) / B) * 2))
    return fx

def loop_bridge(segs, B, ovs, max_out=21.0):
    """Every video loops. Appends a bridge that plays the frames just *before* the opening shot, with the opening
    camera framing, so the last frame flows straight into the first (no dissolve needed). The timeline is whole bars,
    so the cyclic music loop (music.py) and the picture wrap on the same downbeat."""
    g0 = segs[0]; total = sum(g.dur for g in segs); beats = int(round(total / B))
    need = BRIDGE['need'] if BRIDGE['need'] is not None else bridge_beats(beats, B, max_out); BRIDGE['need'] = None
    if need:
        dur = need * B; r0 = max(.05, g0.speed_at(0.0)); a1 = min(g0.a, g0.b); want = r0 * dur
        a0 = max(getattr(g0, 'm_a', 0.0) - getattr(g0, 'm_lead', 0.0), a1 - want, 0.0)  # lead_in = same-shot footage before the moment
        c = engine_cam(g0, 0.0)
        cam = dict(zoom0=c['zoom'], zoom1=c['zoom'], cx0=c['cx'], cx1=c['cx'], cy0=c['cy'], cy1=c['cy'], rot0=c['rot'], rot1=c['rot'], ease='lin')
        if a1 - a0 >= .5 * want:
            br = Seg(a0, a1, dur, cam=cam, tag='bridge', src=g0.src)
        else:  # no usable lead-in: boomerang (play the opening backwards into the start) so it keeps moving
            span = min(want, abs(g0.b - g0.a) * .6)
            br = Seg(a1, a1 + max(span, .01), dur, cam=cam, tag='bridge', src=g0.src, reverse=True)
        if g0.split is not None:
            s2 = g0.split; c2 = engine_cam(s2, 0.0); r2 = max(.05, s2.speed_at(0.0)); b1 = min(s2.a, s2.b)
            br.split = Seg(max(0.0, b1 - r2 * dur), b1, dur, cam=dict(zoom0=c2['zoom'], zoom1=c2['zoom'], cx0=c2['cx'], cx1=c2['cx'], cy0=c2['cy'], cy1=c2['cy']), src=s2.src)
            br.split_mode = g0.split_mode
        br.fx = set(); br.moment = getattr(g0, 'moment', None)
        old_end = total; segs.append(br); new_end = total + dur
        for o in ovs:  # end cards stay up through the bridge, then dissolve into the hook text
            if o.t1 >= old_end - .06: o.t1 = new_end
    return 0.0  # no crossfade: picture continuity comes from the bridge, sound continuity from the cyclic mix

TARGET = {'s': 15.0}   # set per video by build.py: video "target_s" > plan "target_s" > NATURAL[format]
# Natural length per format (2026 roundups, directional): 7-15 s = "viral sweet spot" with the highest completion
# (esp. Reels); 15-30 s = strongest TikTok engagement band, Shorts completion peaks ~20-25 s. Visual/rewatch formats
# sit in 9-15 s; formats that carry information or a story get 16-20 s. Ceiling = plan "max_s" (default 30).
NATURAL = {'result_first': 15, 'pov_story': 17, 'velocity': 13, 'satisfying_loop': 10, 'transformation': 10,
           'listicle': 18, 'myth_fact': 16, 'quiz': 9, 'asmr': 15, 'montage': 11, 'timelapse_timer': 11,
           'ingredient_count': 12, 'compilation': 14, 'kinetic_story': 20, 'split_compare': 10}
STRETCH = (0.8, 1.35)  # max uniform tempo change; beyond this slow-mo and music start to feel wrong

BRIDGE = {'need': None}  # bridge length decided in fit_to_target, reused by loop_bridge (must agree)

def bridge_beats(beats, B, max_out=20.0):
    """beats to append as the loop bridge so the whole timeline is whole bars (music-first: video = N bars of a
    cyclic music loop). Prefer a real bridge (1-4 beats) so the picture flows back into the opening shot."""
    need = (-beats) % 4
    if need == 0 and (beats + 4) * B <= max_out: need = 4
    if need and (beats + need) * B > max_out: need = 0
    return need

def fit_to_target(segs, B, ovs, hits, reveal, freeze, music, extra):
    """Uniformly re-time the whole edit (cuts, text, effects, music tempo) so the looped output lands on the target
    length. Same edit, slightly slower/faster tempo; beat sync is preserved because B scales too. The final length is
    snapped to a multiple of AAC_FRAMES video frames, so the AAC soundtrack has no padding at the loop seam."""
    beats = int(round(sum(g.dur for g in segs) / B)); tgt = TARGET['s']
    need = bridge_beats(beats, B, max_out=tgt * 2); BRIDGE['need'] = need
    out_beats = beats + need          # whole bars, no crossfade: the video IS the music cycle
    k = min(max(tgt / (out_beats * B), STRETCH[0]), STRETCH[1])
    q = AAC_FRAMES / FPS; k = max(1, round(out_beats * B * k / q)) * q / (out_beats * B)  # snap length to the AAC grid
    for g in segs:
        g.dur *= k
        if g.split is not None: g.split.dur *= k
    for o in ovs: o.t0 *= k; o.t1 *= k
    hits = [(t * k, s_) for t, s_ in hits]; reveal = reveal * k if reveal is not None else None
    freeze = freeze * k if freeze is not None else None
    music = dict(music or {}); music.update({x: music[x] * k for x in ('drop', 'build') if music.get(x) is not None})
    ex = (lambda f: (lambda img, t: f(img, t / k)))(extra) if extra else None
    return B * k, hits, reveal, freeze, music, ex

def finish(segs, B, ovs, hits=(), reveal=None, freeze=None, music=None, grade='warm', extra=None, loop=None, nat=1.0, sfx_whip=True, vo_windows=None):
    B, hits, reveal, freeze, music, extra = fit_to_target(segs, B, ovs, list(hits), reveal, freeze, music, extra)
    loop = loop_bridge(segs, B, ovs, max_out=TARGET['s'] + 1.0)  # mandatory seamless loop for every format
    tl = Timeline(segs); tl.B = B
    return dict(tl=tl, overlays=ovs, fx=make_fx(tl, hits, reveal, freeze), grade=make_grade_named(grade), extra=extra,
                audio=dict(music=music or {}, hits=list(hits), reveal=reveal, freeze=freeze, nat=nat, whip=sfx_whip), loop=loop,
                vo_windows=vo_windows or [])

def bpm_of(opt, style): return opt.get('bpm') or DEFAULT_BPM[style]

# ================================================================== formats
def result_first(M, C, opt):
    """Payoff first + bold claim, numbered steps on the beat, reveal, CTA tail that loops into the hook."""
    need(C, 'hook', 'reveal_big', 'cta'); K = KITS[opt.get('kit', 'bold')]
    style = opt.get('music', 'upbeat'); B = 60 / bpm_of(opt, style)
    hook_m = M.get(opt['hook_moment']) if opt.get('hook_moment') else M.first('macro', 'result')
    segs = [seg(M, hook_m, 4 * B, 'slow', cam=dict(zoom0=1.0, zoom1=1.1), fx={'pulse'})]
    steps = M.steps()[:opt.get('max_steps', 7)]
    for j, m in enumerate(steps):
        d = 2 * B
        segs.append(seg(M, m, d, 'slowhit' if j in (0, len(steps) // 2, len(steps) - 1) else 'snap', fx=({'punch'} if j % 2 == 0 else set()) | ({'whip'} if j % 3 == 1 else set())))
    proc = M.last_process()
    if proc: segs.append(seg(M, proc, 2 * B, 'span', rate=4.0, cam=dict(zoom0=1.0, zoom1=1.12)))
    rev = M.first('reveal') or M.first('result')
    segs.append(seg(M, rev, 4 * B, 'normal', cam=dict(zoom0=1.06, zoom1=1.0, ease='out')))
    tail = M.first('result') or rev
    segs.append(seg(M, tail, 4 * B, 'span', rate=.4, cam=dict(zoom0=1.0, zoom1=1.04), fx={'pulse'}))
    S = np.cumsum([0] + [g.dur for g in segs]); r_i = len(segs) - 2
    ovs = [ov(K.headline(C['hook']), .05, S[1] - .02, y=.27, anim='slam', pop=True)]
    for j, m in enumerate(steps):
        ovs.append(ov(K.chip(f'{j + 1:02d}', C.get('labels', {}).get(m['id'], m.get('label', m['id']))), S[j + 1], S[j + 2], y=.17, anim='slide', slide=-60))
    ovs.append(ov(K.big(C['reveal_big'], 200), S[r_i] + .2, S[r_i + 1] - .02, y=.25, anim='slam', pop=True))
    if C.get('reveal_sub'): ovs.append(ov(K.caption(C['reveal_sub'], 54), S[r_i] + .9, S[r_i + 1] - .02, y=.355, anim='rise'))
    ovs.append(ov(K.headline(C['cta'], 84), S[r_i + 1] + .05, S[-1], y=.21, anim='pop'))
    hits = [(S[j + 1] + hit_out(segs[j + 1], m), .8) for j, m in enumerate(steps) if segs[j + 1]._v.min() < .5]
    return finish(segs, B, ovs, hits, reveal=S[r_i], music=dict(style=style, drop=S[r_i], build=2 * B), grade=opt.get('grade', 'warm'), loop=.3)

def pov_story(M, C, opt):
    """Relatable story told through 4-6 captions; freeze-frame callout on the twist; tape-stop then drop on reveal."""
    need(C, 'lines', 'freeze_word', 'punch', 'cta'); K = KITS[opt.get('kit', 'native')]
    style = opt.get('music', 'lofi'); B = 60 / bpm_of(opt, style)
    hook_m = M.get(opt['hook_moment']) if opt.get('hook_moment') else M.steps()[min(2, len(M.steps()) - 1)]
    hero = M.get(opt['hero_moment']) if opt.get('hero_moment') else M.first('before') or M.steps()[0]
    segs = [seg(M, hook_m, 4 * B, 'slow', rate=1.0, cam=dict(zoom0=1.3, zoom1=1.12))]
    segs.append(seg(M, hero, 2 * B, 'snap'))
    segs.append(seg(M, hero, 2 * B, 'freeze', cam=dict(zoom0=1.3, zoom1=1.55, ease='out'), tag='freeze'))
    mids = [m for m in M.steps() if m['id'] not in (hook_m['id'], hero['id'])][:5]
    for j, m in enumerate(mids): segs.append(seg(M, m, (2 if j == len(mids) - 1 else 1) * B, 'snap' if j % 2 else 'span', rate=1.6, fx={'punch'} if j % 2 == 0 else set()))
    proc = M.last_process()
    if proc: segs.append(seg(M, proc, 2 * B, 'span', rate=5.0, cam=dict(zoom0=1.2, zoom1=1.3)))
    rev = M.first('reveal') or M.first('result'); segs.append(seg(M, rev, 5 * B, 'normal', cam=dict(zoom0=1.08, zoom1=1.0, ease='out')))
    tail = M.first('macro', 'result'); segs.append(seg(M, tail, 4 * B, 'span', rate=.5))
    S = np.cumsum([0] + [g.dur for g in segs]); L = C['lines']; fz = 2; rv = len(segs) - 2
    # captions: line0 hook, line1 before freeze, rest spread over the middle until reveal
    ovs = [ov(K.caption(L[0], 78), .05, S[1] - .02, y=.24, anim='fade', pop=True),
           ov(K.caption(L[1], 72), S[1], S[2] - .02, y=.26, anim='rise')]
    ovs.append(ov(K.big(C['freeze_word'], 230), S[fz] + .05, S[fz + 1] - .02, y=.24, anim='slam', rot=-4, pop=True))
    ovs.append(ov(circle_img(), S[fz] + .2, S[fz + 1] - .02, y=.52, anim='pop', rot=-6))
    rest = L[2:]; span0, span1 = S[fz + 1], S[rv]
    for j, ln in enumerate(rest):
        a = span0 + (span1 - span0) * j / len(rest); b = span0 + (span1 - span0) * (j + 1) / len(rest)
        ovs.append(ov(K.caption(ln, 70), a, b - .03, y=.26, anim='rise'))
    ovs.append(ov(K.big(C['punch'], 150), S[rv] + .02, S[rv + 1] - .02, y=.24, anim='slam', rot=-3, pop=True))
    ovs.append(ov(K.headline(C['cta'], 86), S[rv + 1] + .1, S[-1], y=.22, anim='pop'))
    freeze_gray = lambda img, t: cv2.addWeighted(img, .55, cv2.cvtColor(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR), .45, 0) if S[fz] <= t < S[fz + 1] else img
    gr = grain_extra(7)
    return finish(segs, B, ovs, [(S[rv] + .02, 1.3)], reveal=S[rv], freeze=S[fz],
                  music=dict(style=style, drop=S[rv], build=0, tapestop=True), grade=opt.get('grade', 'film'),
                  extra=lambda img, t: gr(freeze_gray(img, t), t), loop=0)

def velocity(M, C, opt):
    """Velocity/phonk: every shot rushes in and snaps to slow-mo on the hit; ingredient list stacks up; curiosity hook."""
    need(C, 'hook_small', 'hook_big', 'reveal_small', 'reveal_big', 'cta'); K = KITS[opt.get('kit', 'editorial')]
    style = opt.get('music', 'phonk'); B = 60 / bpm_of(opt, style)
    hook_m = M.get(opt['hook_moment']) if opt.get('hook_moment') else M.first('macro', 'result')
    segs = [seg(M, hook_m, 5 * B, 'slow', cam=dict(zoom0=1.25, zoom1=1.1), fx={'pulse'})]
    steps = M.steps()[:opt.get('max_steps', 7)]
    for j, m in enumerate(steps): segs.append(seg(M, m, (4 if j == len(steps) - 1 else 2) * B, 'velocity', fx={'punch', 'whip'}))
    proc = M.last_process()
    if proc: segs.append(seg(M, proc, 2 * B, 'span', rate=7.0, cam=dict(zoom0=1.25, zoom1=1.1)))
    rev = M.first('reveal') or M.first('result'); segs.append(seg(M, rev, 6 * B, 'normal', cam=dict(zoom0=1.08, zoom1=1.0, ease='out')))
    tail = M.first('result'); segs.append(seg(M, tail, 4 * B, 'span', rate=.5, fx={'pulse'}))
    S = np.cumsum([0] + [g.dur for g in segs]); rv = len(segs) - 2
    ovs = [ov(K.headline(C['hook_small'], 100), .05, S[1] - .02, y=.21, anim='rise'),
           ov(K.big(C['hook_big'], 240), .45, S[1] - .02, y=.31, anim='slam', pop=True)]
    hits = []
    for j, m in enumerate(steps):
        ht = S[j + 1] + hit_out(segs[j + 1], m); hits.append((ht, 1.0))
        hero = m.get('hero', False) or j == len(steps) - 1
        ovs.append(ov(K.item(C.get('labels', {}).get(m['id'], m.get('label', m['id'])), hero), ht, S[rv] - .02, x=.075, y=.17 + j * .042, anchor='left', anim='slide', slide=-40))
    ovs.append(ov(K.headline(C['reveal_small'], 100), S[rv] + .1, S[rv + 1] - .02, y=.17, anim='rise'))
    ovs.append(ov(K.big(C['reveal_big'], 270), S[rv] + .5, S[rv + 1] - .02, y=.27, anim='slam', pop=True))
    if C.get('reveal_sub'): ovs.append(ov(K.caption(C['reveal_sub'], 46), S[rv] + 1.1, S[rv + 1] - .02, y=.355, anim='fade'))
    ovs.append(ov(K.headline(C['cta'], 84), S[rv + 1] + .05, S[-1], y=.21, anim='rise'))
    return finish(segs, B, ovs, hits + [(.45, 1.2)], reveal=S[rv], music=dict(style=style, drop=S[rv], build=B), grade=opt.get('grade', 'teal'), loop=.25)

def satisfying_loop(M, C, opt):
    """Satisfying sequence: slow, story-free run of satisfying actions (one bar each), seamless loop, ~20 s."""
    K = KITS[opt.get('kit', 'minimal')]; style = opt.get('music', 'ambient'); B = 60 / bpm_of(opt, style)
    ids = opt.get('moments') or [m['id'] for m in rot(M.steps(), opt)][:opt.get('count', 5)]
    each = opt.get('beats_each', 4) * B
    segs = [seg(M, M.get(i), each, 'slowhit' if M.get(i)['kind'] == 'action' else 'slow', rate=opt.get('rate', 1.0),
                cam=dict(zoom0=1.2 if j % 2 else 1.1, zoom1=1.1 if j % 2 else 1.2)) for j, i in enumerate(ids)]
    ovs = [ov(K.caption(C['line'], 64), .45, sum(g.dur for g in segs), y=.2, anim='fade')] if C.get('line') else []
    return finish(segs, B, ovs, music=dict(style=style), grade=opt.get('grade', 'clean'), loop=.4, nat=1.6, sfx_whip=False)

def transformation(M, C, opt):
    """Before holds while tension builds, cut one beat before the drop to the after, then a split before/after, loop."""
    need(C, 'before', 'after'); K = KITS[opt.get('kit', 'grotesk')]; style = opt.get('music', 'cinematic'); B = 60 / bpm_of(opt, style)
    bef = M.get(opt['before_moment']) if opt.get('before_moment') else M.first('before')
    aft = M.get(opt['after_moment']) if opt.get('after_moment') else (M.first('reveal') or M.first('result'))
    res = M.first('result', 'macro')
    s1 = seg(M, bef, 6 * B, 'slow', rate=.8, cam=dict(zoom0=1.1, zoom1=1.35))
    mids = [seg(M, m, B, 'snap', fx={'whip'} if j % 2 else set()) for j, m in enumerate(M.steps()[:opt.get('max_steps', 6)])]
    s2 = seg(M, aft, 4 * B, 'normal', cam=dict(zoom0=1.06, zoom1=1.0, ease='out'))
    s3 = seg(M, bef, 6 * B, 'slow', rate=.6, cam=dict(zoom0=1.3, zoom1=1.25))
    s3.split = seg(M, res, 6 * B, 'span', rate=.4, cam=dict(zoom0=1.15, zoom1=1.2)); s3.split.dur = s3.dur
    segs = [s1] + mids + [s2, s3]; S = np.cumsum([0] + [g.dur for g in segs]); a_i = len(segs) - 2
    ovs = [ov(K.headline(C['before'], 96), .35, S[1] - .02, y=.22, anim='rise'),
           ov(K.headline(C['after'], 96), S[a_i] + .15, S[a_i + 1] - .02, y=.22, anim='slam', pop=True),
           ov(K.label(C.get('label_before', 'SEBELUM')), S[a_i + 1], S[a_i + 2], y=.29, anim='fade'),
           ov(K.label(C.get('label_after', 'SESUDAH')), S[a_i + 1], S[a_i + 2], y=.79, anim='fade')]
    return finish(segs, B, ovs, reveal=S[a_i], music=dict(style=style, drop=S[a_i], build=len(mids) * B), grade=opt.get('grade', 'moody'))

def listicle(M, C, opt):
    """Numbered list ("3 hal ..."): title hook, one item per 2-3 s over matching b-roll, CTA."""
    need(C, 'title', 'items', 'cta'); K = KITS[opt.get('kit', 'rounded')]; style = opt.get('music', 'house'); B = 60 / bpm_of(opt, style)
    hook_m = M.get(opt['hook_moment']) if opt.get('hook_moment') else M.first('result', 'macro')
    pool = [M.get(i) for i in opt['item_moments']] if opt.get('item_moments') else M.steps()[1::2] + M.kind('process')
    segs = [seg(M, hook_m, 4 * B, 'slow', cam=dict(zoom0=1.0, zoom1=1.1))]
    for j, _ in enumerate(C['items']):
        m = pool[j % len(pool)]; segs.append(seg(M, m, opt.get('beats_each', 7) * B, 'slowhit' if m['kind'] == 'action' else 'span', rate=2.0, fx={'punch'} if j else set()))
    end = M.first('result'); segs.append(seg(M, end, 4 * B, 'span', rate=.5))
    S = np.cumsum([0] + [g.dur for g in segs])
    ovs = [ov(K.headline(C['title'], 100), .05, S[1] - .02, y=.25, anim='slam', pop=True)]
    for j, it in enumerate(C['items']):
        ovs.append(ov(K.number(str(j + 1), 220), S[j + 1] + .02, S[j + 2] - .02, x=.16, y=.2, anim='pop', pop=True))
        ovs.append(ov(K.caption(it, 66), S[j + 1] + .25, S[j + 2] - .02, y=.31, anim='rise'))
    ovs.append(ov(K.headline(C['cta'], 84), S[-2] + .05, S[-1], y=.22, anim='pop'))
    return finish(segs, B, ovs, music=dict(style=style), grade=opt.get('grade', 'pop'), loop=.25)

def myth_fact(M, C, opt):
    """MITOS card (desaturated, tense) -> FAKTA flips it with proof shots -> conclusion."""
    need(C, 'myth', 'fact', 'proof', 'cta'); K = KITS[opt.get('kit', 'grotesk')]; style = opt.get('music', 'cinematic'); B = 60 / bpm_of(opt, style)
    mm = M.get(opt['myth_moment']) if opt.get('myth_moment') else M.first('before')
    proofs = [M.get(i) for i in opt['proof_moments']] if opt.get('proof_moments') else M.steps()[-3:]
    segs = [seg(M, mm, 6 * B, 'slow', rate=.7, cam=dict(zoom0=1.3, zoom1=1.15), tag='myth')]
    for j, m in enumerate(proofs): segs.append(seg(M, m, 2 * B, 'slowhit', fx={'punch'}))
    rev = M.first('reveal') or M.first('result'); segs.append(seg(M, rev, 4 * B, 'normal', cam=dict(zoom0=1.06, zoom1=1.0, ease='out')))
    end = M.first('macro', 'result'); segs.append(seg(M, end, 4 * B, 'span', rate=.5))
    S = np.cumsum([0] + [g.dur for g in segs]); np_ = len(proofs)
    ovs = [ov(K.label('MITOS', 64), .05, S[1] - .02, y=.18, anim='pop', pop=True), ov(K.headline(C['myth'], 84), .3, S[1] - .02, y=.27, anim='rise'),
           ov(K.label('FAKTA', 64), S[1], S[np_ + 2] - .02, y=.18, anim='slam', pop=True), ov(K.headline(C['fact'], 84), S[1] + .2, S[np_ + 1], y=.27, anim='rise')]
    for j, p in enumerate(C['proof'][:np_]): ovs.append(ov(K.caption(p, 62), S[1 + j] + .1, S[2 + j] - .02, y=.36, anim='fade'))
    ovs.append(ov(K.headline(C['cta'], 84), S[-2] + .05, S[-1], y=.22, anim='pop'))
    myth_gray = lambda img, t: cv2.addWeighted(img, .35, cv2.cvtColor(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR), .65, 0) if t < S[1] else img
    return finish(segs, B, ovs, reveal=S[np_ + 1], music=dict(style=style, drop=S[1], build=2 * B), grade=opt.get('grade', 'moody'), extra=myth_gray)

def quiz(M, C, opt):
    """'Tebak ini apa?': ambiguous extreme close-up, 3-2-1 on the beat, zoom-out answer, fast proof recap, comment bait."""
    need(C, 'question', 'answer', 'cta'); K = KITS[opt.get('kit', 'native')]; style = opt.get('music', 'phonk'); B = 60 / bpm_of(opt, style)
    close = M.get(opt['close_moment']) if opt.get('close_moment') else M.first('macro', 'result')
    segs = [seg(M, close, 8 * B, 'slow', rate=.6, cam=dict(zoom0=2.2, zoom1=1.9))]
    rev = M.first('reveal') or M.first('result'); segs.append(seg(M, rev, 4 * B, 'normal', cam=dict(zoom0=1.1, zoom1=1.0, ease='out')))
    for j, m in enumerate(M.steps()): segs.append(seg(M, m, 2 * B, 'snap', fx={'punch'} if j % 2 == 0 else {'whip'}))
    end = M.first('result'); segs.append(seg(M, end, 4 * B, 'span', rate=.5))
    S = np.cumsum([0] + [g.dur for g in segs])
    ovs = [ov(K.headline(C['question'], 100), .05, S[1] - .02, y=.24, anim='slam', pop=True)]
    for j, n in enumerate(['3', '2', '1']): ovs.append(ov(K.number(n, 260), S[1] - (3 - j) * B, S[1] - (2 - j) * B - .02, y=.5, anim='slam', pop=True))
    ovs.append(ov(K.big(C['answer'], 190), S[1] + .1, S[2] - .02, y=.26, anim='slam', pop=True))
    if C.get('answer_sub'): ovs.append(ov(K.caption(C['answer_sub'], 56), S[1] + .7, S[-2], y=.36, anim='rise'))
    ovs.append(ov(K.headline(C['cta'], 84), S[-2] + .05, S[-1], y=.22, anim='pop'))
    return finish(segs, B, ovs, reveal=S[1], music=dict(style=style, drop=S[1], build=B), grade=opt.get('grade', 'pop'))

def asmr(M, C, opt):
    """Quiet, slow, sound-first: long takes, slow-mo hits without shake, tiny lowercase labels, near-silent bed."""
    K = KITS[opt.get('kit', 'minimal')]; style = opt.get('music', 'ambient'); B = 60 / bpm_of(opt, style)
    ids = opt.get('moments') or [m['id'] for m in rot(M.steps(), opt)][:5]
    segs = [seg(M, M.get(i), 3 * B if j % 2 else 4 * B, 'slowhit' if M.get(i)['kind'] == 'action' else 'span', rate=1.0, cam=dict(zoom0=1.12, zoom1=1.2)) for j, i in enumerate(ids)]
    res = M.first('macro', 'result'); segs.append(seg(M, res, 5 * B, 'span', rate=.4))
    S = np.cumsum([0] + [g.dur for g in segs]); ovs = []
    if C.get('line'): ovs.append(ov(K.caption(C['line'], 56), .3, S[1], y=.2, anim='fade'))
    if C.get('labels', True):
        for j, i in enumerate(ids):
            lab = (C.get('labels') if isinstance(C.get('labels'), dict) else {}).get(i, M.get(i).get('label', ''))
            if lab: ovs.append(ov(K.caption(lab.lower(), 56), S[j] + .3, S[j + 1] - .1, y=.72, anim='fade'))
    return finish(segs, B, ovs, music=dict(style=style, gain=.35), grade=opt.get('grade', 'film'), extra=grain_extra(4), nat=2.2, sfx_whip=False, loop=.3)

def montage(M, C, opt):
    """Montage to music: 10-15 one-beat cuts ordered by vibe, hero clip on the drop, one framing line."""
    K = KITS[opt.get('kit', 'minimal')]; style = opt.get('music', 'house'); B = 60 / bpm_of(opt, style)
    pool = rot(M.steps() + M.kind('process', 'macro'), opt)
    segs = []
    for j, m in enumerate(pool[:opt.get('cuts', 12)]): segs.append(seg(M, m, opt.get('beats_each', 2) * B, 'snap' if m['kind'] == 'action' else 'span', rate=2.0, fx={'whip'} if j % 4 == 3 else set()))
    hero = M.first('reveal') or M.first('result'); segs.append(seg(M, hero, 4 * B, 'normal', cam=dict(zoom0=1.08, zoom1=1.0, ease='out'), fx={'punch'}))
    end = M.first('macro', 'result'); segs.append(seg(M, end, 3 * B, 'span', rate=.5, fx={'pulse'}))
    S = np.cumsum([0] + [g.dur for g in segs]); hv = len(segs) - 2; ovs = []
    if C.get('line'): ovs.append(ov(K.caption(C['line'], 70), .05, S[3], y=.22, anim='fade'))
    if C.get('end_line'): ovs.append(ov(K.headline(C['end_line'], 92), S[hv] + .1, S[-1], y=.22, anim='rise', pop=True))
    return finish(segs, B, ovs, reveal=S[hv], music=dict(style=style, drop=S[hv], build=B), grade=opt.get('grade', 'pop'), loop=.25)

class _Timer:
    """renders mm:ss of *footage time* (honest: it's recording time, not cooking time) from pre-rendered glyphs"""
    def __init__(s, kit, size=84):
        s.g = {c: np.array(text_layer(c, F(kit.head, size), fill=kit.fill, stroke=max(4, kit.stroke), shadow=0)) for c in '0123456789:.'}
        s.w = max(v.shape[1] for k, v in s.g.items() if k.isdigit())
    def draw(s, img, txt, x, y):
        for c in txt:
            gl = s.g[c]; h, w = gl.shape[:2]; a = gl[..., 3:4] / 255.
            roi = img[y:y + h, x:x + w].astype(np.float32)
            img[y:y + h, x:x + w] = (roi * (1 - a) + gl[..., :3][..., ::-1] * a).astype(np.uint8)
            x += (s.w if c.isdigit() else w) - 6
        return img

def timelapse_timer(M, C, opt):
    """The whole process compressed in order with a running footage-time counter, then the result."""
    need(C, 'hook', 'end_line'); K = KITS[opt.get('kit', 'grotesk')]; style = opt.get('music', 'house'); B = 60 / bpm_of(opt, style)
    steps = [M.by[i] for i in M.order]
    segs = [seg(M, m, 2 * B, 'span', rate=max(1.5, (m['b'] - m['a']) / (2 * B)), cam=dict(zoom0=1.1, zoom1=1.1), fx={'punch'} if j % 4 == 0 else set()) for j, m in enumerate(steps)]
    rev = M.first('reveal') or M.first('result'); segs.append(seg(M, rev, 4 * B, 'normal', cam=dict(zoom0=1.06, zoom1=1.0, ease='out')))
    end = M.first('result'); segs.append(seg(M, end, 3 * B, 'span', rate=.5))
    tl0 = Timeline(segs); S = tl0.starts; tmr = _Timer(K)
    t0src = steps[0]['a']
    def extra(img, t):
        if t >= S[len(steps)]: return img
        i, g, u = tl0.at(t); sec = max(0, g.src_time(u) - t0src)
        return tmr.draw(img, f'{int(sec // 60):02d}:{sec % 60:05.2f}', 300, int(H * .29))
    ovs = [ov(K.headline(C['hook'], 88), .05, S[len(steps)] - .02, y=.2, anim='pop', pop=True),
           ov(K.headline(C['end_line'], 96), S[len(steps)] + .1, S[-1], y=.22, anim='slam', pop=True)]
    return finish(segs, B, ovs, reveal=S[len(steps)], music=dict(style=style, drop=S[len(steps)], build=0), grade=opt.get('grade', 'clean'), extra=extra)

def ingredient_count(M, C, opt):
    """Big counter ticks up on each ingredient hit (1..N) with its name; then the result."""
    need(C, 'hook', 'end_line'); K = KITS[opt.get('kit', 'bold')]; style = opt.get('music', 'upbeat'); B = 60 / bpm_of(opt, style)
    hook_m = M.get(opt['hook_moment']) if opt.get('hook_moment') else M.first('result', 'macro')
    steps = M.steps()[:opt.get('max_steps', 7)]
    segs = [seg(M, hook_m, 4 * B, 'slow')] + [seg(M, m, 3 * B, 'snap', fx={'punch'} if j % 2 == 0 else set()) for j, m in enumerate(steps)]
    rev = M.first('reveal') or M.first('result'); segs.append(seg(M, rev, 4 * B, 'normal', cam=dict(zoom0=1.06, zoom1=1.0, ease='out')))
    S = np.cumsum([0] + [g.dur for g in segs])
    ovs = [ov(K.headline(C['hook'], 104), .05, S[1] - .02, y=.25, anim='slam', pop=True)]; hits = []
    for j, m in enumerate(steps):
        ht = S[j + 1] + hit_out(segs[j + 1], m); hits.append((ht, .7))
        ovs.append(ov(K.number(str(j + 1), 280), ht - .1, S[j + 2] - .02, x=.5, y=.2, anim='slam', pop=True))
        ovs.append(ov(K.caption(C.get('labels', {}).get(m['id'], m.get('label', m['id'])), 70), ht, S[j + 2] - .02, y=.31, anim='rise'))
    ovs.append(ov(K.headline(C['end_line'], 96), S[-2] + .15, S[-1], y=.22, anim='slam', pop=True))
    return finish(segs, B, ovs, hits, reveal=S[-2], music=dict(style=style, drop=S[-2], build=B), grade=opt.get('grade', 'warm'))

def compilation(M, C, opt):
    """Ranked countdown of the best moments (can mix several footage files via moments' src): N..1 then the #1 hero."""
    need(C, 'title', 'items'); K = KITS[opt.get('kit', 'rounded')]; style = opt.get('music', 'lofi'); B = 60 / bpm_of(opt, style)
    ids = opt.get('moments') or [m['id'] for m in M.steps()][-len(C['items']):]
    n = len(ids); segs = [seg(M, M.get(ids[0]), 3 * B, 'slow', cam=dict(zoom0=1.25, zoom1=1.1))]
    for j, i in enumerate(ids):
        m = M.get(i); segs.append(seg(M, m, (5 if j == n - 1 else 4) * B, 'slowhit' if m['kind'] == 'action' else 'span', rate=1.0, fx={'punch'}))
    S = np.cumsum([0] + [g.dur for g in segs])
    ovs = [ov(K.headline(C['title'], 96), .05, S[1] - .02, y=.25, anim='slam', pop=True)]
    for j, it in enumerate(C['items'][:n]):
        ovs.append(ov(K.number(f'#{n - j}', 200), S[j + 1] + .02, S[j + 2] - .02, x=.2, y=.19, anim='slam', pop=True))
        ovs.append(ov(K.caption(it, 62), S[j + 1] + .3, S[j + 2] - .02, y=.29, anim='rise'))
    if C.get('cta'): ovs.append(ov(K.caption(C['cta'], 58), S[-2] + .5, S[-1], y=.36, anim='fade'))
    return finish(segs, B, ovs, [(S[j + 1] + hit_out(segs[j + 1], M.get(i)), .6) for j, i in enumerate(ids) if M.get(i)['kind'] == 'action'],
                  music=dict(style=style), grade=opt.get('grade', 'film'), loop=.25)

def kinetic_story(M, C, opt):
    """Text carries a micro-story (6-9 short lines) changing on the bar; footage is b-roll cut on the beat."""
    need(C, 'lines'); K = KITS[opt.get('kit', 'editorial')]; style = opt.get('music', 'lofi'); B = 60 / bpm_of(opt, style)
    pool = rot(M.steps() + M.kind('process'), opt); L = C['lines']; per = opt.get('beats_per_line', 4)
    segs = []
    for j in range(len(L) * per // 2): segs.append(seg(M, pool[j % len(pool)], 2 * B, 'span', rate=1.5))
    rev = M.first('reveal') or M.first('result'); segs.append(seg(M, rev, 4 * B, 'normal', cam=dict(zoom0=1.06, zoom1=1.0, ease='out')))
    S = np.cumsum([0] + [g.dur for g in segs]); ovs = []
    for j, ln in enumerate(L):
        a = j * per * B; b = min((j + 1) * per * B, S[-2]) if j < len(L) - 1 else S[-1]
        ovs.append(ov(K.headline(ln, 130) if j in (0, len(L) - 1) else K.caption(ln, 124), a + .02, b - .03, y=.3 if j else .27, anim='rise', pop=j in (0, len(L) - 1)))
    return finish(segs, B, ovs, reveal=S[-2], music=dict(style=style), grade=opt.get('grade', 'film'), extra=grain_extra(5))

def split_compare(M, C, opt):
    """Whole video split screen: process on top, the result building on the bottom (or any two sequences)."""
    need(C, 'top', 'bottom'); K = KITS[opt.get('kit', 'bold')]; style = opt.get('music', 'upbeat'); B = 60 / bpm_of(opt, style)
    tops = rot(M.steps(), opt)[:opt.get('max_steps', 7)]; bot = M.kind('result', 'macro', 'reveal')
    segs = []
    for j, m in enumerate(tops):
        g = seg(M, m, 3 * B, 'snap', fx={'punch'} if j % 2 == 0 else set()); g.split = seg(M, bot[j % len(bot)], 3 * B, 'span', rate=.5); g.split.dur = g.dur
        segs.append(g)
    res = M.first('reveal') or M.first('result'); segs.append(seg(M, res, 4 * B, 'normal', cam=dict(zoom0=1.06, zoom1=1.0, ease='out')))
    S = np.cumsum([0] + [g.dur for g in segs])
    ovs = [ov(K.label(C['top']), .05, S[-2], y=.27, anim='pop', pop=True), ov(K.label(C['bottom']), .05, S[-2], y=.77, anim='pop')]
    if C.get('end_line'): ovs.append(ov(K.headline(C['end_line'], 92), S[-2] + .1, S[-1], y=.22, anim='slam', pop=True))
    return finish(segs, B, ovs, reveal=S[-2], music=dict(style=style, drop=S[-2], build=B), grade=opt.get('grade', 'clean'))

FORMATS = {f.__name__: f for f in [result_first, pov_story, velocity, satisfying_loop, transformation, listicle, myth_fact, quiz,
                                    asmr, montage, timelapse_timer, ingredient_count, compilation, kinetic_story, split_compare]}
