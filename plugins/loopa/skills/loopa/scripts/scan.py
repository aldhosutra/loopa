"""Scan a folder of raw footage, group clips into units, and prepare one workspace per unit.

Grouping:
  * a folder below ROOT that directly contains videos = ONE unit (already categorised by the user)
  * videos lying loose in ROOT may be an uncategorised mix: they are clustered into proposed groups using
    capture time (same recording session), filename sequence and visual similarity. The proposal is written to
    WS/groups.json + WS/roster.jpg (one row of thumbnails per clip). Review it (look at roster.jpg), fix
    groups.json (move clips, rename groups, "skip" junk), then run scan again: an existing groups.json is respected.
  * skipped: the workspace, folders starting with '_' or '.', and --exclude names (e.g. old edits)

Per-clip analysis (probe, capture time, scene cuts, loudness, overview sheet, thumbnails, visual signature) is cached
in WS/_cache, so regrouping and rescans are cheap. Existing moments.json / plan.json are never overwritten.

Per unit WS/<unit_id>/: footage.json, moments.draft.json (one 'todo' moment per detected shot), sheets -> overview grids.
usage: python3 -I scan.py ROOT [--ws ROOT/_shorts] [--exclude short,old] [--gap 20] [--regroup]"""
import sys, os, re, json, subprocess, argparse, math, hashlib, datetime
import numpy as np
VIDEO = ('.mov', '.mp4', '.m4v', '.mkv', '.avi', '.webm', '.mts', '.3gp')

def slug(s): return re.sub(r'[^a-z0-9]+', '_', s.lower()).strip('_')[:40] or 'clip'

# ------------------------------------------------------------------ per-clip analysis (cached)
def probe(p):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                        'format=duration:format_tags=creation_time,com.apple.quicktime.creationdate:stream=codec_type,width,height,avg_frame_rate,codec_name:stream_side_data=rotation:stream_tags=rotate',
                        '-of', 'json', p], capture_output=True, text=True)
    d = json.loads(r.stdout or '{}'); st = d.get('streams', []); tags = d.get('format', {}).get('tags', {})
    v = next((x for x in st if x.get('codec_type') == 'video'), {}); a = any(x.get('codec_type') == 'audio' for x in st)
    rot = 0
    for sd in v.get('side_data_list', []) or []:
        if 'rotation' in sd: rot = int(float(sd['rotation']))
    rot = rot or int(v.get('tags', {}).get('rotate', 0) or 0)
    w, h = v.get('width', 0), v.get('height', 0)
    if abs(rot) % 180 == 90: w, h = h, w
    num, den = (v.get('avg_frame_rate', '30/1') or '30/1').split('/')
    fps = float(num) / float(den) if float(den or 0) else 30.0
    ct, ct_src = None, 'mtime'
    for k in ('com.apple.quicktime.creationdate', 'creation_time'):
        if tags.get(k):
            try:
                ct = datetime.datetime.fromisoformat(tags[k].replace('Z', '+00:00')).timestamp(); ct_src = k; break
            except ValueError: pass
    if ct is None: ct = os.path.getmtime(p)
    return dict(duration=round(float(d.get('format', {}).get('duration', 0) or 0), 3), width=w, height=h, fps=round(fps, 3),
                rotation=rot, codec=v.get('codec_name'), audio=a, capture_ts=ct, capture_src=ct_src,
                orientation='vertical' if h > w else 'horizontal' if w > h else 'square')

def scene_cuts(p, thr):
    r = subprocess.run(['ffmpeg', '-hide_banner', '-i', p, '-vf', f"scale=270:-2,select='gt(scene,{thr})',showinfo", '-an', '-f', 'null', '-'], capture_output=True, text=True)
    return [round(float(x), 2) for x in re.findall(r'pts_time:([0-9.]+)', r.stderr)]

def loudness(p):
    r = subprocess.run(['ffmpeg', '-v', 'error', '-i', p, '-ac', '1', '-ar', '8000', '-f', 's16le', '-'], capture_output=True)
    a = np.frombuffer(r.stdout, np.int16).astype(np.float32) / 32768
    return [round(float(20 * np.log10(np.sqrt((a[i:i + 8000] ** 2).mean()) + 1e-9)), 1) for i in range(0, len(a), 8000)]

def frames_at(p, times, w=160):
    out = []
    for t in times:
        r = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{t:.2f}', '-i', p, '-frames:v', '1', '-vf', f'scale={w}:-2', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True)
        h = len(r.stdout) // (w * 3)
        if h: out.append(np.frombuffer(r.stdout[:w * h * 3], np.uint8).reshape(h, w, 3))
    return out

def signature(frames):
    """visual fingerprint: HSV colour histogram + coarse layout of a few frames (cosine-comparable)"""
    import cv2
    feats = []
    for f in frames:
        hsv = cv2.cvtColor(f, cv2.COLOR_RGB2HSV)
        hist = cv2.calcHist([hsv], [0, 1, 2], None, [12, 4, 4], [0, 180, 0, 256, 0, 256]).flatten(); hist /= hist.sum() + 1e-9
        lay = cv2.resize(cv2.cvtColor(f, cv2.COLOR_RGB2GRAY), (6, 10), interpolation=cv2.INTER_AREA).flatten().astype(np.float32) / 255
        feats.append(np.concatenate([np.sqrt(hist) * 2, lay - lay.mean()]))
    v = np.mean(feats, 0) if feats else np.zeros(12 * 4 * 4 + 60)
    return (v / (np.linalg.norm(v) + 1e-9)).tolist()

def analyze(p, ws, thr):
    st = os.stat(p); key = hashlib.md5(f'{p}|{st.st_size}|{int(st.st_mtime)}'.encode()).hexdigest()[:12]
    cdir = os.path.join(ws, '_cache'); os.makedirs(cdir, exist_ok=True); cj = os.path.join(cdir, key + '.json')
    if os.path.exists(cj): return json.load(open(cj))
    m = probe(p); m.update(path=p, file=os.path.basename(p), key=key)
    m['cuts'] = scene_cuts(p, thr); m['loudness_db_per_s'] = loudness(p)
    d = m['duration']; fps = 1 if d <= 120 else .5; n = max(1, math.ceil(d * fps)); rows = math.ceil(n / 10)
    m['sheet'] = os.path.join(cdir, key + '_overview.jpg'); m['sheet_fps'] = fps
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', p, '-vf', f'fps={fps},scale=180:-1,tile=10x{rows}', '-frames:v', '1', m['sheet']])
    thumbs = frames_at(p, [d * x for x in (.08, .3, .5, .7, .92)])
    m['signature'] = signature(thumbs)
    if thumbs:
        from PIL import Image
        hh = min(t.shape[0] for t in thumbs); strip = np.hstack([t[:hh] for t in thumbs])
        m['strip'] = os.path.join(cdir, key + '_strip.jpg'); Image.fromarray(strip).save(m['strip'], quality=85)
    json.dump(m, open(cj, 'w'))
    return m

# ------------------------------------------------------------------ grouping of loose clips
def seq_num(name):
    m = re.findall(r'(\d{3,})', name); return int(m[-1]) if m else None

def propose_groups(clips, gap_min):
    """sort by capture time; a clip joins the previous group when it was shot in the same session (gap <= gap_min)
    and looks related, or when it's the next filename in sequence and looks related; very similar clips join anyway."""
    cs = sorted(clips, key=lambda m: (m['capture_ts'], m['file']))
    times_ok = len({round(m['capture_ts']) for m in cs}) > 1 and any(m['capture_src'] != 'mtime' for m in cs)
    groups = []
    for m in cs:
        best, best_s, why = None, -1, ''
        for g in groups:
            sims = [float(np.dot(m['signature'], o['signature'])) for o in g['clips_m']]
            s = max(sims); last = g['clips_m'][-1]
            gap = (m['capture_ts'] - last['capture_ts'] - last['duration']) / 60
            seq = seq_num(m['file']) is not None and seq_num(last['file']) is not None and 0 < seq_num(m['file']) - seq_num(last['file']) <= 3
            if times_ok and gap <= gap_min and s >= .72: r = f'same session ({gap:.0f} min gap), look similar ({s:.2f})'
            elif seq and s >= .72: r = f'filename sequence, look similar ({s:.2f})'
            elif s >= .9: r = f'very similar look ({s:.2f})'
            else: continue
            if s > best_s: best, best_s, why = g, s, r
        if best: best['clips_m'].append(m); best['why'].append(f"{m['file']}: {why}")
        else: groups.append({'clips_m': [m], 'why': [f"{m['file']}: starts group"]})
    out = []
    for i, g in enumerate(groups, 1):
        files = [m['file'] for m in g['clips_m']]
        gid = slug(os.path.splitext(files[0])[0]) if len(files) == 1 else f'mix_g{i:02d}'
        out.append({'id': gid, 'clips': files, 'why': g['why']})
    return out, times_ok

def roster(ws, clips, groups):
    """one row per clip: 5 thumbnails + file, capture time, duration, proposed group"""
    from PIL import Image, ImageDraw, ImageFont
    g_of = {f: g['id'] for g in groups for f in g['clips']}
    rows = []
    for m in sorted(clips, key=lambda m: (g_of.get(m['file'], ''), m['capture_ts'])):
        if not m.get('strip'): continue
        im = Image.open(m['strip']); row = Image.new('RGB', (im.width + 520, max(im.height, 140)), (20, 20, 20)); row.paste(im, (520, 0))
        d = ImageDraw.Draw(row); ts = datetime.datetime.fromtimestamp(m['capture_ts']).strftime('%Y-%m-%d %H:%M')
        try: fnt = ImageFont.load_default(size=22)
        except TypeError: fnt = ImageFont.load_default()
        for k, t in enumerate([f"[{g_of.get(m['file'], '?')}]", m['file'], f"{ts} ({m['capture_src']})", f"{m['duration']:.0f}s {m['width']}x{m['height']} {m['fps']:g}fps"]):
            d.text((10, 8 + k * 30), t, fill=(255, 220, 60) if k == 0 else (235, 235, 235), font=fnt)
        rows.append(row)
    if not rows: return None
    W_ = max(r.width for r in rows); out = Image.new('RGB', (W_, sum(r.height + 4 for r in rows)), (0, 0, 0)); y = 0
    for r in rows: out.paste(r, (0, y)); y += r.height + 4
    p = os.path.join(ws, 'roster.jpg'); out.save(p, quality=85); return p

# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(); ap.add_argument('root'); ap.add_argument('--ws'); ap.add_argument('--exclude', default='')
    ap.add_argument('--scene', type=float, default=.3); ap.add_argument('--gap', type=float, default=20, help='max minutes between clips of one session')
    ap.add_argument('--regroup', action='store_true', help='ignore an existing groups.json and propose again'); a = ap.parse_args()
    root = os.path.abspath(a.root); ws = os.path.abspath(a.ws or os.path.join(root, '_shorts')); os.makedirs(ws, exist_ok=True)
    exclude = set(x for x in a.exclude.split(',') if x)
    folder_units, loose = [], []
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if not x.startswith(('_', '.')) and os.path.join(d, x) != ws and x not in exclude)
        vids = sorted(os.path.join(d, f) for f in files if f.lower().endswith(VIDEO) and not f.startswith('.'))
        if not vids: continue
        if os.path.abspath(d) == root: loose = vids
        else: folder_units.append((slug(os.path.relpath(d, root)), vids))
    allp = [p for _, v in folder_units for p in v] + loose
    print(f'{len(allp)} clips: {len(folder_units)} folder unit(s), {len(loose)} loose clip(s) in root')
    meta = {}
    for i, p in enumerate(allp, 1):
        print(f'  [{i}/{len(allp)}] {os.path.relpath(p, root)}', flush=True); meta[p] = analyze(p, ws, a.scene)
    units = [(uid, vids, 'folder') for uid, vids in folder_units]
    gp = os.path.join(ws, 'groups.json')
    if loose:
        by_file = {os.path.basename(p): p for p in loose}
        if os.path.exists(gp) and not a.regroup:
            gj = json.load(open(gp)); groups = gj['groups']; print(f'using reviewed {gp}')
            known = {f for g in groups for f in g['clips']} | set(gj.get('skip', []))
            for f in sorted(set(by_file) - known):  # new loose files since the review -> own group, flagged
                groups.append({'id': slug(os.path.splitext(f)[0]), 'clips': [f], 'why': ['NEW since last review']}); print(f'  new clip, not in groups.json: {f}')
        else:
            groups, times_ok = propose_groups([meta[p] for p in loose], a.gap)
            gj = {'_help': 'Proposed grouping of loose clips. Check roster.jpg; move files between groups, rename ids (they become '
                           'unit/workspace names), put junk in "skip", then rerun scan.py. reviewed=true marks it as checked.',
                  'reviewed': False, 'capture_times_reliable': times_ok, 'groups': groups, 'skip': []}
            json.dump(gj, open(gp, 'w'), indent=1, ensure_ascii=False)
            print(f'proposed {len(groups)} group(s) from {len(loose)} loose clips -> {gp}' + ('' if times_ok else '  (no capture times: grouped by look only)'))
        rp = roster(ws, [meta[p] for p in loose], groups); print(f'roster: {rp}')
        if not gj.get('reviewed'): print('!! groups.json is a PROPOSAL: review roster.jpg before planning (set "reviewed": true)')
        for g in groups:
            vids = [by_file[f] for f in g['clips'] if f in by_file]
            if vids: units.append((slug(g['id']), sorted(vids, key=lambda p: (meta[p]['capture_ts'], p)), 'group'))
    inv = {'root': root, 'workspace': ws, 'units': []}
    for uid, vids, origin in units:
        ud = os.path.join(ws, uid); os.makedirs(ud, exist_ok=True)
        footage, moments, order, fmeta = {}, [], [], []
        for ci, p in enumerate(vids, 1):
            m = meta[p]; key = f'c{ci}'; fmeta.append(dict({k: v for k, v in m.items() if k != 'signature'}, name=key))
            footage[key] = {'path': p, 'cuts': m['cuts'], **({} if m['orientation'] == 'vertical' else {'crop': [.5, .5]})}
            bounds = [0.0] + [c for c in m['cuts'] if .4 < c < m['duration'] - .4] + [m['duration']]
            for si in range(len(bounds) - 1):
                if bounds[si + 1] - bounds[si] < .4: continue
                mid = f'{key}_s{si + 1:02d}'; order.append(mid)
                moments.append({'id': mid, 'src': key, 'a': round(bounds[si], 2), 'b': round(bounds[si + 1], 2), 'kind': 'todo', 'label': ''})
        json.dump(fmeta, open(os.path.join(ud, 'footage.json'), 'w'), indent=1)
        json.dump({'footage': footage, 'moments': moments, 'process_order': order,
                   '_help': 'kind: before|action|process|result|reveal|macro|skip; add label/hit/focus; split long shots; '
                            'lead_in is derived from scene cuts unless set. Save the finished map as moments.json.'},
                  open(os.path.join(ud, 'moments.draft.json'), 'w'), indent=1, ensure_ascii=False)
        status = 'plan.json' if os.path.exists(os.path.join(ud, 'plan.json')) else 'moments.json' if os.path.exists(os.path.join(ud, 'moments.json')) else 'draft'
        inv['units'].append({'id': uid, 'origin': origin, 'clips': [os.path.relpath(p, root) for p in vids], 'sheets': [meta[p]['sheet'] for p in vids],
                             'total_s': round(sum(meta[p]['duration'] for p in vids), 1), 'workspace': ud, 'status': status})
        print(f'== {uid} [{origin}] {len(vids)} clip(s), {inv["units"][-1]["total_s"]}s, {sum(len(meta[p]["cuts"]) for p in vids)} cuts -> {status}')
    json.dump(inv, open(os.path.join(ws, 'units.json'), 'w'), indent=1)
    print(f'\n{len(units)} unit(s) -> {os.path.join(ws, "units.json")}')

if __name__ == '__main__':
    main()
