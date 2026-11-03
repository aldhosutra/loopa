"""Batch builder: plan.json + moments.json -> many shorts, rendered one at a time (resumable).

usage:
  python3 -I build.py PLAN.json --check            # build every spec, print durations + diversity report, render nothing
  python3 -I build.py PLAN.json                    # render all missing videos (skips files that already exist)
  python3 -I build.py PLAN.json --only id1,id2 [--force]

plan.json:
{ "moments": "moments.json", "out_dir": "../", "tmp_dir": "/tmp/x", "tts_python": "/path/.ttsenv/bin/python",
  "videos": [ {"id": "v01_tanpa_nasi", "format": "result_first", "angle": "diet",
               "opt": {"kit": "bold", "music": "upbeat", "grade": "warm", "hook_moment": "macro", ...},
               "key": 0, "seed": 1,
               "copy": {...format keys...},
               "vo": {"voice": "em_alex", "speed": 1.12, "lines": ["...", "..."]},        # optional -> dubbed version
               "post": {"caption": "...", "hashtags": "#..."} } ] }"""
import sys, os, json, csv, subprocess, argparse, itertools, shutil
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import *
from formats import FORMATS, Moments
from music import music, tape_stop
HERE = os.path.dirname(os.path.abspath(__file__))

def tool_python(plan, key, env_names, default_dir):
    """env python for an optional tool: plan key > env var > ~/.loopa/<tool> (made by install.sh --with-rife/--with-tts)"""
    for c in [plan.get(key)] + [os.environ.get(e) for e in env_names] + [os.path.expanduser(f'~/.loopa/{default_dir}/bin/python')]:
        if c and os.path.exists(c): return c
    return None

PLAN_TARGET, MAX_S, MIN_S = None, 30.0, 4.0  # 3-7 s loops are a legit, very shareable niche
MIN_FREE_GB = 1.5
def build_spec(v, M):
    if v['format'] not in FORMATS: raise SystemExit(f"{v['id']}: unknown format {v['format']} (have {sorted(FORMATS)})")
    opt = dict(v.get('opt', {}))
    import formats as _f
    _f.TARGET['s'] = min(MAX_S, float(v.get('target_s') or PLAN_TARGET or _f.NATURAL.get(v['format'], 15)))
    return FORMATS[v['format']](M, v.get('copy', {}), opt)

def vo_windows(spec, lines, T):
    """lines: str (auto) or {"text", "at"} where at = moment id | 'hook' | 'reveal' | 'end' | seconds.
    Anchored lines start at their segment; free lines share the gaps in proportion to their length."""
    tl = spec['tl']; loop = spec['loop']; lo, hi = loop + .05, T - loop - .4  # speech ends before the build->drop at the loop point
    def anchor(at):
        if isinstance(at, (int, float)): return float(at)
        if at == 'hook': return lo
        if at == 'reveal' and spec['audio'].get('reveal') is not None: return spec['audio']['reveal'] + .25
        if at == 'end': return tl.starts[-2] + .1
        for k, g in enumerate(tl.segs):
            if getattr(g, 'moment', None) == at: return max(lo, tl.starts[k] + .05)
        raise SystemExit(f'vo anchor {at!r} not found in this video')
    items = [l if isinstance(l, dict) else {'text': l} for l in lines]
    starts = [anchor(it['at']) if 'at' in it else None for it in items]
    if starts[0] is None: starts[0] = lo
    k = 0
    while k < len(items):  # fill runs of free lines between anchors
        if starts[k] is None:
            j = k
            while j < len(items) and starts[j] is None: j += 1
            a0 = starts[k - 1]; b0 = starts[j] if j < len(items) else hi
            w = [len(items[i - 1]['text'])] + [len(items[i]['text']) for i in range(k, j)]
            tot = sum(w); acc = a0
            for i in range(k, j):
                acc += (b0 - a0) * w[i - k] / tot; starts[i] = acc
            k = j
        k += 1
    ends = [(starts[i + 1] - .12) if i + 1 < len(starts) else hi for i in range(len(starts))]
    return [(round(float(s_), 3), round(float(e), 3), it['text']) for s_, e, it in zip(starts, ends, items)]

def make_audio(spec, v, vo=None):
    """Music-first cyclic soundtrack. The timeline is N whole bars; the music is composed as an N-bar cycle (drop on
    bar 0, build on the last bar, harmony resolving into the top) and every layer is rendered tail-to-front:
    anything ringing past the end (notes, SFX, voice reverb, room reverb) is laid over the start. The result is an
    exactly periodic waveform: on replay the sound simply keeps going. No crossfade, no fade, no patch."""
    from music import fold, circular_reverb
    tl = spec['tl']; T = tl.dur; a = spec['audio']; m = a['music']; B = tl.B
    style = m.get('style', 'upbeat'); drop = m.get('drop'); build = m.get('build', 0)
    nf = round(T * FPS); P = nf / FPS; Ps = int(round(P * SR))          # sample-exact to the rendered frames
    mus, beats = music(style, P, 60 / B, key=v.get('key', 0), seed=v.get('seed', 0), brk_at=drop, brk=build)
    if m.get('tapestop') and drop and drop - 2 * B > 0: mus = tape_stop(mus, drop - 2 * B, drop)
    mus = mus * m.get('gain', 1.0)
    n = Ps + int(4 * SR); sfx = np.zeros(n)
    for k, g in enumerate(tl.segs):
        if k and 'whip' in getattr(g, 'fx', ()) and a.get('whip', True): place(sfx, whoosh(.3, True, .22), tl.starts[k] - .15)
    for ht, s_ in a['hits']: place(sfx, impact(.6, .3 * s_), ht)
    if a.get('freeze') is not None: place(sfx, impact(.8, .55), a['freeze']); place(sfx, whoosh(.3, True, .25), a['freeze'] - .15)
    if a.get('reveal') is not None:
        place(sfx, impact(1.6, .9), a['reveal']); place(sfx, swish_ding(.15), a['reveal'] + .05)
        if build: place(sfx, riser(build + .05, .4), a['reveal'] - build)
    for o in spec['overlays']:
        if getattr(o, 'pop', False) and o.t0 > .1: place(sfx, pop(.2), o.t0)
    # the loop point is the drop: a riser climbs through the build bar and an impact lands on bar 0 (it rings into
    # the next cycle via the fold, exactly like a drop in a song)
    rs = min(4 * B, P / 3); place(sfx, riser(rs, .3), P - rs)
    place(sfx, impact(1.4, .7), P)
    sfx = fold(sfx, Ps)
    nat = src_audio_track(tl, total=P, gain=a.get('nat', 1.0))[:Ps]; nat = np.pad(nat, (0, Ps - len(nat)))
    if vo is not None:
        from captions import place_vo
        voa, regions = place_vo(vo, n); voa = fold(voa, Ps)
        bed = duck(mus, regions, .55) * .8 + sfx * .55 + duck(nat, regions, .5) * .7
        mix = circular_reverb(bed, .08) + voa
    else:
        mix = circular_reverb(mus * .8 + sfx * .7 + nat * .8, .08)
    return limiter(mix / (np.abs(mix).max() + 1e-9) * 1.3)   # memoryless -> stays periodic

def run_vo(v, spec, plan, workdir):
    tl = spec['tl']; win = vo_windows(spec, v['vo']['lines'], tl.dur)
    js = {'voice': v['vo'].get('voice', 'ef_dora'), 'speed': v['vo'].get('speed', 1.1),
          'lines': [{'t': a, 'end': b, 'text': t} for a, b, t in win]}
    d = os.path.join(workdir, 'vo_' + v['id']); os.makedirs(d, exist_ok=True)
    jp = os.path.join(d, 'spec.json'); vj = os.path.join(d, 'vo.json')
    if os.path.exists(jp) and os.path.exists(vj) and json.load(open(jp)) == json.loads(json.dumps(js)):
        print('vo: reusing generated voice (script + windows unchanged)'); return json.load(open(vj))
    json.dump(js, open(jp, 'w'), indent=1)
    py = tool_python(plan, 'tts_python', ('LOOPA_TTS_PY', 'SHORTS_TTS_PY'), 'tts')
    if not py: raise SystemExit('dubbing needs the TTS env: run install.sh --with-tts (or scripts/setup_tts.sh ~/.loopa/tts)')
    r = subprocess.run([py, os.path.join(HERE, 'make_vo.py'), jp, d], capture_output=True, text=True)
    print('\n'.join(l for l in r.stdout.splitlines() if l.startswith('[')))
    if r.returncode: raise SystemExit(r.stderr[-2000:])
    return json.load(open(os.path.join(d, 'vo.json')))

def first_sig(spec):
    g = spec['tl'].segs[0]; return getattr(g, 'moment', None)

def shot_set(spec):
    s = set()
    for g in spec['tl'].segs:
        for gg in [g] + ([g.split] if g.split is not None else []):
            lo, hi = sorted((gg.a, gg.b)); s.update(range(int(lo * 2), int(hi * 2) + 1))  # half-second bins
    return s

def check(plan, specs, M=None):
    vids = plan['videos']; ok = True
    print(f"\n{'id':28s} {'format':16s} {'angle':10s} {'dur':>5s}  hook-shot      kit/grade/music")
    for v, sp in zip(vids, specs):
        dur = sp['tl'].dur - sp['loop']; o = v.get('opt', {})
        flag = f'  <-- outside {MIN_S:.0f}-{MAX_S:.0f} s' if not MIN_S <= dur <= MAX_S + .5 else ''
        ok &= MIN_S <= dur <= MAX_S + .5
        print(f"{v['id']:28s} {v['format']:16s} {v.get('angle', ''):10s} {dur:5.1f}  {str(first_sig(sp)):14s} {o.get('kit', '-')}/{o.get('grade', '-')}/{sp['audio']['music'].get('style')}{flag}")
    print('\ndiversity:')
    ids = [v['id'] for v in vids]
    if len(set(ids)) != len(ids): print('  ✗ duplicate ids'); ok = False
    combos = {}
    for v, sp in zip(vids, specs):
        combos.setdefault((v['format'], v.get('angle')), []).append(v['id'])
    for k, l in combos.items():
        if len(l) > 1: print(f'  ✗ same format+angle {k}: {l}'); ok = False
    opening, shot_use = {}, {}
    for v, sp in zip(vids, specs):
        opening.setdefault((first_sig(sp), v['format']), []).append(v['id'])
        shot_use.setdefault(first_sig(sp), []).append(v['id'])
    for k, l in opening.items():
        if len(l) > 1: print(f'  ✗ same opening shot + format {k}: {l}  (first 2 s must differ)'); ok = False
    for k, l in shot_use.items():
        if len(l) > 2: print(f'  ✗ opening shot {k!r} used {len(l)}x: {l}  (max 2; use hook_moment / rotate)'); ok = False
    audio = {}
    for v, sp in zip(vids, specs): audio.setdefault((sp['audio']['music'].get('style'), v.get('key', 0), v.get('seed', 0)), []).append(v['id'])
    for k, l in audio.items():
        if len(l) > 1: print(f'  ✗ identical music bed {k}: {l}  (change key or seed)'); ok = False
    # one footage -> recipe videos naturally share shots. That's fine when format/hook/copy/audio differ.
    # It's a near-duplicate only when shots overlap heavily AND the format is the same (unless marked variant_of).
    sets = [shot_set(sp) for sp in specs]; rows = []
    for (i, a), (j, b) in itertools.combinations(enumerate(sets), 2):
        jac = len(a & b) / max(1, len(a | b)); vi, vj = vids[i], vids[j]
        same_fmt = vi['format'] == vj['format']
        variant = vi.get('variant_of') == vj['id'] or vj.get('variant_of') == vi['id']
        rows.append((jac, ids[i], ids[j], same_fmt, variant))
    rows.sort(reverse=True)
    for jac, a, b, same_fmt, variant in rows:
        if same_fmt and jac > .6:
            if variant: print(f'  ~ variant  {jac:4.0%}  {a} ~ {b}  (intentional; post them days apart)')
            else: print(f'  ✗ near-duplicate {jac:4.0%}  {a} ~ {b}  (same format + same shots: change format, or mark variant_of)'); ok = False
    print(f'  max shot overlap across different formats: {max([r[0] for r in rows if not r[3]] or [0]):.0%} (ok: shared footage)')
    if M is not None:  # a segment that spans a source scene cut shows a hard camera jump mid-shot (and breaks loop bridges)
        seen = set()
        for v, sp in zip(vids, specs):
            for g in sp['tl'].segs:
                for gg in [g] + ([g.split] if g.split is not None else []):
                    mid = getattr(gg, 'moment', None); m = M.by.get(mid) if mid else None
                    if not m: continue
                    lo, hi = sorted((gg.a, gg.b)); cuts = [c for c in M.cuts.get(m.get('src', 'main'), []) if lo + .05 < c < hi - .05]
                    if cuts and (mid, round(lo, 1)) not in seen:
                        seen.add((mid, round(lo, 1))); ok = False
                        print(f"  ✗ {v['id']}: moment '{mid}' plays {lo:.2f}-{hi:.2f}s across a scene cut at {cuts} (split the moment at the cut)")
    print('\nOK' if ok else '\nFIX the ✗ items before rendering'); return ok

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('plan'); ap.add_argument('--check', action='store_true')
    ap.add_argument('--only'); ap.add_argument('--force', action='store_true')
    ap.add_argument('--audio-only', action='store_true', help='rebuild + remux the soundtrack of existing videos (no video re-render)')
    args = ap.parse_args()
    pdir = os.path.dirname(os.path.abspath(args.plan)); plan = json.load(open(args.plan))
    global PLAN_TARGET, MAX_S; PLAN_TARGET = plan.get('target_s'); MAX_S = float(plan.get('max_s', 30))
    mp = os.path.join(pdir, plan.get('moments', 'moments.json')); M = Moments(json.load(open(mp)))
    out = os.path.abspath(os.path.join(pdir, plan.get('out_dir', 'out'))); os.makedirs(out, exist_ok=True)
    tmp = os.path.join(pdir, plan.get('tmp_dir') or '_tmp'); os.makedirs(tmp, exist_ok=True)  # relative to the plan file
    vids = plan['videos']
    if args.only: vids = [v for v in vids if v['id'] in args.only.split(',')]
    if args.check:
        specs = [build_spec(v, M) for v in vids]; sys.exit(0 if check(dict(plan, videos=vids), specs, M) else 1)
    rows = []
    for v in vids:
        name = v['id'] + ('_DUB' if v.get('vo') else '') + '.mp4'; path = os.path.join(out, name)
        spec = build_spec(v, M); dur = spec['tl'].dur - spec['loop']
        rows.append([name, v['format'], v.get('angle', ''), f'{dur:.1f}', v.get('post', {}).get('caption', ''), v.get('post', {}).get('hashtags', ''), 'yes' if v.get('vo') else 'no'])
        if args.audio_only:
            if not os.path.exists(path): print(f'skip (not rendered yet) {name}'); continue
            vo = None
            if v.get('vo'):
                win = vo_windows(spec, v['vo']['lines'], spec['tl'].dur); jp = os.path.join(tmp, 'vo_' + v['id'], 'spec.json')
                want = [{'t': x, 'end': y, 'text': t} for x, y, t in win]
                if not os.path.exists(jp) or json.load(open(jp)).get('lines') != json.loads(json.dumps(want)):
                    print(f'needs full re-render (voice timing changed, burned-in captions would drift): {name}  -> --only {v["id"]} --force'); continue
                vo = run_vo(v, spec, plan, tmp)
            wav = os.path.join(tmp, v['id'] + '.wav'); write_wav(wav.replace('.wav', '_n.wav'), normalize_periodic(make_audio(spec, v, vo)))
            tmpv = path + '.audio.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', path, '-i', wav.replace('.wav', '_n.wav'), '-map', '0:v', '-map', '1:a', '-c:v', 'copy',
                            '-c:a', 'aac', '-b:a', '256k', '-shortest', '-movflags', '+faststart', tmpv], check=True)
            os.replace(tmpv, path); print(f'audio rebuilt {name}', flush=True); continue
        if os.path.exists(path) and not args.force: print(f'skip (exists) {name}'); continue
        free = shutil.disk_usage(out).free / 1e9
        if free < MIN_FREE_GB:
            print(f'STOP: only {free:.1f} GB free on disk (need >= {MIN_FREE_GB} GB for frame generation + encoding). '
                  f'Free some space, then rerun: finished videos are skipped.'); break
        print(f'=== {name}  [{v["format"]}] {dur:.1f}s', flush=True)
        vo = None
        if v.get('vo'):
            vo = run_vo(v, spec, plan, tmp)
            from captions import word_captions
            spec['overlays'] = [o for o in spec['overlays'] if getattr(o, 'role', None) != 'caption'] + word_captions(vo, y=.70)
        wav = os.path.join(tmp, v['id'] + '_n.wav'); write_wav(wav, normalize_periodic(make_audio(spec, v, vo)))  # -14 LUFS, still periodic
        fg = None
        rpy = tool_python(plan, 'rife_python', ('LOOPA_RIFE_PY', 'SHORTS_RIFE_PY'), 'rife')
        if rpy and os.path.exists(rpy):
            fg = {'py': rpy, 'model': plan.get('rife_model') or os.path.join(os.path.dirname(os.path.dirname(rpy)), 'rife-models', 'rife-v4.26'),
                  'dir': os.path.join(tmp, 'framegen')}
        elif not getattr(main, '_warned', False):
            print('!! RIFE not found: slow motion falls back to optical flow. Run install.sh --with-rife (or scripts/setup_rife.sh ~/.loopa/rife)'); main._warned = True
        rc = render(spec['tl'], path, wav, spec['overlays'], fx=spec['fx'], grade=spec['grade'], extra_frame=spec['extra'], loop_blend=spec['loop'], framegen=fg)
        print('done' if rc == 0 else f'FAILED rc={rc}', name, flush=True)
    mpath = os.path.join(out, 'manifest.csv'); old = {}
    if os.path.exists(mpath):
        for r in csv.reader(open(mpath)): old[r[0]] = r
    for r in rows: old[r[0]] = r
    with open(mpath, 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['file', 'format', 'angle', 'seconds', 'caption', 'hashtags', 'dubbed'])
        for k, r in old.items():
            if k != 'file': w.writerow(r)
    print('manifest:', mpath)

if __name__ == '__main__':
    main()
