"""Run the whole workflow over every unit found by scan.py, one render at a time (resumable).

usage:
  python3 -I build_all.py WS --merge     # write WS/_all/moments.json = every unit's moments (ids prefixed '<unit_id>.')
  python3 -I build_all.py WS --check     # --check every unit plan (and WS/_all/plan.json if present)
  python3 -I build_all.py WS             # render every unit plan, then _all; writes WS/manifest_all.csv
  options: --units u01_x,u03_y  --force

A unit is ready when WS/<unit>/plan.json exists (moments.json beside it). WS/_all/plan.json holds cross-unit videos
(ranked compilations, 'best of' montages, series) that use moments from several units."""
import sys, os, json, csv, subprocess, argparse
HERE = os.path.dirname(os.path.abspath(__file__))

def merge(ws, units):
    footage, moments, order = {}, [], []
    for u in units:
        mp = os.path.join(u['workspace'], 'moments.json')
        if not os.path.exists(mp): print(f'  (no moments.json yet) {u["id"]}'); continue
        d = json.load(open(mp)); pre = u['id']
        for k, v in d['footage'].items(): footage[f'{pre}.{k}'] = v
        for m in d['moments']:
            m = dict(m, id=f"{pre}.{m['id']}", src=f"{pre}.{m.get('src', 'main')}", unit=u['id']); moments.append(m)
        order += [f'{pre}.{i}' for i in d.get('process_order', [])]
    os.makedirs(os.path.join(ws, '_all'), exist_ok=True)
    out = os.path.join(ws, '_all', 'moments.json')
    json.dump({'footage': footage, 'moments': moments, 'process_order': order}, open(out, 'w'), indent=1, ensure_ascii=False)
    print(f'merged {len(moments)} moments from {len(units)} units -> {out}')

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('ws'); ap.add_argument('--merge', action='store_true')
    ap.add_argument('--check', action='store_true'); ap.add_argument('--units'); ap.add_argument('--force', action='store_true')
    a = ap.parse_args(); ws = os.path.abspath(a.ws)
    inv = json.load(open(os.path.join(ws, 'units.json'))); units = inv['units']
    if a.units: units = [u for u in units if u['id'] in a.units.split(',')]
    if a.merge: merge(ws, inv['units']); return
    jobs = [(u['id'], os.path.join(u['workspace'], 'plan.json')) for u in units]
    jobs.append(('_all', os.path.join(ws, '_all', 'plan.json')))
    bad = 0
    for uid, plan in jobs:
        if not os.path.exists(plan):
            if uid != '_all': print(f'-- {uid}: no plan.json yet, skipped')
            continue
        print(f'\n######## {uid}', flush=True)
        cmd = [sys.executable, '-I', os.path.join(HERE, 'build.py'), plan] + (['--check'] if a.check else []) + (['--force'] if a.force else [])
        bad += subprocess.run(cmd).returncode != 0
    if a.check: print('\nALL OK' if not bad else f'\n{bad} plan(s) need fixes'); sys.exit(1 if bad else 0)
    rows = []
    for uid, plan in jobs:
        if not os.path.exists(plan): continue
        p = json.load(open(plan)); mp = os.path.join(os.path.dirname(plan), p.get('out_dir', 'out'), 'manifest.csv')
        if os.path.exists(mp):
            r = list(csv.reader(open(mp)))
            rows += [[uid, os.path.join(os.path.dirname(mp), x[0])] + x[1:] for x in r[1:]]
    with open(os.path.join(ws, 'manifest_all.csv'), 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['unit', 'file', 'format', 'angle', 'seconds', 'caption', 'hashtags', 'dubbed']); w.writerows(rows)
    print(f'\n{len(rows)} videos total -> {os.path.join(ws, "manifest_all.csv")}')

if __name__ == '__main__':
    main()
