"""AI frame generation for slow motion (RIFE, ncnn/Vulkan on the GPU). Run with the RIFE env python (setup_rife.sh).
Called by engine.render(): it receives every in-between frame the edit needs (source pair + timestep) and writes
real generated frames to a cache, so slow-mo looks like high-frame-rate footage instead of stretched 30 fps.

usage: RIFE_PY framegen.py REQUEST.json
REQUEST: {"model": "/abs/rife-models/rife-v4.26", "items": [{"src", "crop": [cx, cy], "i0", "a", "out"}]}"""
import sys, os, json, time
import cv2, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import _fit, W, H
from rife_ncnn_vulkan_python import Rife

req = json.load(open(sys.argv[1]))
items = [it for it in req['items'] if not os.path.exists(it['out'])]
if not items: print('framegen: all frames cached'); sys.exit(0)
t0 = time.time()
rife = Rife(gpuid=0, model=req['model'], num_threads=2, width=W, height=H)
by_src = {}
for it in items: by_src.setdefault(it['src'], []).append(it)
done = 0
for src, its in by_src.items():
    crop = tuple(its[0].get('crop', (.5, .5)))
    need = sorted({it['i0'] for it in its} | {it['i0'] + 1 for it in its})
    cache, cap, idx, k = {}, cv2.VideoCapture(src), 0, 0
    while k < len(need):
        ok, fr = cap.read()
        if not ok: break
        if idx == need[k]:
            cache[idx] = cv2.imencode('.jpg', _fit(fr, *crop), [cv2.IMWRITE_JPEG_QUALITY, 97])[1].tobytes(); k += 1
        idx += 1
    cap.release()
    dec = lambda i: cv2.imdecode(np.frombuffer(cache[min(i, max(cache))], np.uint8), cv2.IMREAD_COLOR)
    its.sort(key=lambda it: (it['i0'], it['a']))
    pair, f0, f1 = None, None, None
    for it in its:
        if pair != it['i0']: f0, f1, pair = dec(it['i0']), dec(it['i0'] + 1), it['i0']
        out = rife.process_cv2(f0, f1, float(it['a']))
        cv2.imwrite(it['out'], out, [cv2.IMWRITE_JPEG_QUALITY, 93]); done += 1
        if done % 50 == 0: print(f'framegen: {done}/{len(items)} frames', flush=True)
print(f'framegen: generated {done} frames in {time.time() - t0:.0f}s ({(time.time() - t0) / max(done, 1):.2f}s/frame)')
