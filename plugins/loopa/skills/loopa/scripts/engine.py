"""Mini shorts render engine: speed-ramped segments, camera moves, grade, kinetic text, synth audio.
Memory-light: source frames cached as JPEG bytes, single optical-flow cache entry."""
import cv2, numpy as np, subprocess, os, math, wave, hashlib, json
from collections import OrderedDict
from PIL import Image, ImageDraw, ImageFont, ImageFilter

SRC = os.environ.get('SHORTS_SRC', '')  # raw footage path; set SHORTS_SRC before running a template
W, H, FPS, SR = 1080, 1920, 30, 48000
AAC_FRAMES = 16  # 16 video frames @30fps = 25600 samples @48k = 25 AAC blocks of 1024 -> no encoder padding at the loop seam
FONTS = os.path.expanduser('~/Library/Fonts/')   # kept for compatibility; font() searches all FONT_DIRS
FONT_DIRS = [os.path.expanduser(p) for p in ('~/Library/Fonts', '/Library/Fonts', '/System/Library/Fonts', '/System/Library/Fonts/Supplemental',
             '~/.local/share/fonts', '~/.fonts', '/usr/local/share/fonts', '/usr/share/fonts')]
FALLBACK_FONTS = ('Avenir Next.ttc', 'HelveticaNeue.ttc', 'Helvetica.ttc', 'DejaVuSans-Bold.ttf', 'LiberationSans-Bold.ttf', 'NotoSans-Bold.ttf')
_FONT_CACHE = {}
def find_font(name):
    """locate a font file by name in the usual macOS/Linux font folders (recursive under /usr/share/fonts)"""
    if name.startswith('/'): return name if os.path.exists(name) else None
    if name in _FONT_CACHE: return _FONT_CACHE[name]
    hit = None
    for d in FONT_DIRS:
        p = os.path.join(d, name)
        if os.path.exists(p): hit = p; break
    if hit is None:
        for d in FONT_DIRS:
            if not os.path.isdir(d) or not d.startswith(('/usr', os.path.expanduser('~/.'))): continue
            for root, _, files in os.walk(d):
                if name in files: hit = os.path.join(root, name); break
            if hit: break
    _FONT_CACHE[name] = hit
    return hit
EMOJI = '/System/Library/Fonts/Apple Color Emoji.ttc'
cv2.setNumThreads(4)

# ---------------------------------------------------------------- easing
def clamp(x, a=0., b=1.): return max(a, min(b, x))
def ease_out(x): x = clamp(x); return 1 - (1 - x) ** 3
def ease_in(x): x = clamp(x); return x ** 3
def ease_io(x): x = clamp(x); return 4*x**3 if x < .5 else 1 - (-2*x+2)**3/2
def back_out(x, s=2.2):
    x = clamp(x); x -= 1; return x*x*((s+1)*x + s) + 1

# ---------------------------------------------------------------- segments
class Seg:
    def __init__(s, a, b, dur, speed=None, cam=None, reverse=False, tag=None, src=None, split=None, split_mode='v'):
        """src: footage path (default SHORTS_SRC) -> compilations can mix clips.
        split: a second Seg shown at the same time (split screen; 'v' = top/bottom, 'h' = left/right)."""
        s.a, s.b, s.dur, s.reverse, s.tag = a, b, dur, reverse, tag
        s.src, s.split, s.split_mode = src, split, split_mode
        if split is not None: split.dur = dur
        s.cam = dict(zoom0=1.0, zoom1=1.0, cx0=.5, cy0=.5, cx1=.5, cy1=.5, rot0=0, rot1=0, ease='io')
        if cam: s.cam.update(cam)
        u = np.linspace(0, 1, 400)
        if speed:
            ku, kv = zip(*speed); v = np.interp(u, ku, kv)
        else:
            v = np.ones_like(u)
        f = np.concatenate([[0], np.cumsum((v[1:] + v[:-1]) / 2)]); f /= f[-1]
        s._u, s._f, s._v = u, f, v / np.trapezoid(v, u)
    def src_time(s, u):
        f = np.interp(u, s._u, s._f)
        if s.reverse: f = 1 - f
        return s.a + (s.b - s.a) * f
    def speed_at(s, u):
        return abs(s.b - s.a) / s.dur * np.interp(u, s._u, s._v)

class Timeline:
    def __init__(s, segs):
        s.segs = segs; s.starts = np.cumsum([0] + [g.dur for g in segs]); s.dur = s.starts[-1]
    def at(s, t):
        i = int(np.searchsorted(s.starts, t, side='right') - 1); i = min(max(i, 0), len(s.segs) - 1)
        g = s.segs[i]; u = clamp((t - s.starts[i]) / g.dur)
        return i, g, u
    def cut_times(s): return list(s.starts[1:-1])

# ---------------------------------------------------------------- frame source
def _need_src():
    if not SRC or not os.path.exists(SRC):
        raise SystemExit(f'SHORTS_SRC not set or missing: {SRC!r} (export SHORTS_SRC=/path/to/raw.mov)')

CROP = {}   # footage path -> (cx, cy) crop centre for non-9:16 footage (set from moments.json footage entries)
_FPS = {}
def src_fps(path):
    """real frame rate of a footage file (24/25/30/60/VFR all map correctly to source frames)"""
    if path not in _FPS:
        cap = cv2.VideoCapture(path); f = cap.get(cv2.CAP_PROP_FPS) or 30.0; cap.release()
        _FPS[path] = f if 1 < f < 241 else 30.0
    return _FPS[path]

def _fit(fr, cx=.5, cy=.5):
    """any footage -> 1080x1920 cover crop around (cx, cy); landscape clips crop to the subject, not blindly to the centre"""
    h, w = fr.shape[:2]
    if (w, h) == (W, H): return fr
    sc = max(W / w, H / h); fr = cv2.resize(fr, (int(w * sc + .5), int(h * sc + .5)), interpolation=cv2.INTER_AREA)
    x0 = int(min(max(cx * fr.shape[1] - W / 2, 0), fr.shape[1] - W)); y0 = int(min(max(cy * fr.shape[0] - H / 2, 0), fr.shape[0] - H))
    return fr[y0:y0 + H, x0:x0 + W]

class FrameSource:
    """needed: {src_path: set(frame_idx)}; frames cached as JPEG bytes."""
    def __init__(s, needed):
        s.cache, s.last, s.fps = {}, {}, {}
        for src, idxs in needed.items():
            if not src or not os.path.exists(src): raise SystemExit(f'footage missing: {src!r} (set SHORTS_SRC or Seg(src=...))')
            need = sorted(i for i in set(idxs) if i >= 0); cap = cv2.VideoCapture(src); idx = 0; k = 0
            while k < len(need):
                ok, fr = cap.read()
                if not ok: break
                while k < len(need) and need[k] < idx: k += 1
                if k < len(need) and need[k] == idx:
                    s.cache[(src, idx)] = cv2.imencode('.jpg', _fit(fr, *CROP.get(src, (.5, .5))), [cv2.IMWRITE_JPEG_QUALITY, 96])[1].tobytes(); k += 1
                idx += 1
            cap.release()
            s.last[src] = max(i for (sp, i) in s.cache if sp == src)
        s.dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
        s.flows = OrderedDict(); s.lru = OrderedDict()
        s.gen = {}  # (src, i0, a) -> path of an AI-generated in-between frame (framegen.py / RIFE)
    def get(s, src, i):
        i = min(max(i, 0), s.last[src])
        while (src, i) not in s.cache and i > 0: i -= 1
        key = (src, i)
        if key in s.lru: s.lru.move_to_end(key); return s.lru[key]
        img = cv2.imdecode(np.frombuffer(s.cache[key], np.uint8), cv2.IMREAD_COLOR)
        s.lru[key] = img
        if len(s.lru) > 6: s.lru.popitem(last=False)
        return img
    def shutter(s, src, ft, speed):
        """fast ramps: blend the source frames this output frame 'skips', like a real 180-degree shutter -> natural motion blur"""
        i0 = int(round(ft)); n = min(5, max(2, int(speed * .6 + .5)))
        acc = np.zeros((H, W, 3), np.float32)
        for j in range(n): acc += s.get(src, i0 - j)
        return (acc / n).astype(np.uint8)
    def interp(s, src, ft, smooth, speed=1.0):
        i0 = int(math.floor(ft)); a = ft - i0
        if speed >= SHUTTER_FROM: return s.shutter(src, ft, speed)
        g = s.gen.get((src, i0, round(a, 4)))
        if smooth and g is not None and os.path.exists(g):
            return cv2.imread(g, cv2.IMREAD_COLOR)
        f0 = s.get(src, i0)
        if not smooth or a < 0.04: return f0
        f1 = s.get(src, i0 + 1)
        if a > 0.96: return f1
        key = (src, i0)
        if key not in s.flows:
            g0 = cv2.cvtColor(cv2.resize(f0, (540, 960)), cv2.COLOR_BGR2GRAY)
            g1 = cv2.cvtColor(cv2.resize(f1, (540, 960)), cv2.COLOR_BGR2GRAY)
            fw = s.dis.calc(g0, g1, None); bw = s.dis.calc(g1, g0, None)
            s.flows[key] = (cv2.resize(fw, (W, H)) * 2, cv2.resize(bw, (W, H)) * 2)
            if len(s.flows) > 2: s.flows.popitem(last=False)
        fw, bw = s.flows[key]; a = np.float32(a)
        w0 = cv2.remap(f0, GX - fw[..., 0] * a, GY - fw[..., 1] * a, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        w1 = cv2.remap(f1, GX - bw[..., 0] * (1 - a), GY - bw[..., 1] * (1 - a), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        return cv2.addWeighted(w0, float(1 - a), w1, float(a), 0)

SHUTTER_FROM = 1.8   # playback speed above which frames get shutter-blended motion blur
GX, GY = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))

# ---------------------------------------------------------------- grade
def make_grade(contrast=1.12, sat=1.25, warm=0.04, lift=0.02, vignette=0.35, gamma=0.97):
    x = np.arange(256) / 255.
    curve = np.clip(0.5 + (x - 0.5) * contrast, 0, 1) ** gamma
    s = 1 / (1 + np.exp(-(x - .5) * 6)); s = (s - s.min()) / (s.max() - s.min())
    curve = np.clip(curve * 0.7 + (s if contrast > 1 else curve) * 0.3, 0, 1)
    curve = lift + curve * (1 - lift)
    luts = [np.clip(curve * (1 - warm) * 255, 0, 255), np.clip(curve * 255, 0, 255), np.clip(curve * (1 + warm) * 255 + warm * 10, 0, 255)]
    lut = np.stack([l.astype(np.uint8) for l in luts], 1).reshape(256, 1, 3)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.sqrt(((xx - W / 2) / (W * .62)) ** 2 + ((yy - H / 2) / (H * .62)) ** 2)
    vig = (1 - vignette * np.clip(d - 0.45, 0, 1) ** 1.6 * 1.8).clip(0, 1)[..., None].astype(np.float32)
    del yy, xx, d
    def apply(img):
        img = cv2.LUT(img, lut); f = img.astype(np.float32)
        if sat != 1:
            g = f.mean(2, keepdims=True); f = g + (f - g) * sat
        f *= vig
        return np.clip(f, 0, 255).astype(np.uint8)
    return apply

# ---------------------------------------------------------------- camera
def camera(img, zoom, cx, cy, rot=0., shake=(0, 0), blur=(0, 0)):
    zoom = max(zoom, 1.0); half = .5 / zoom
    cx = clamp(cx, half, 1 - half); cy = clamp(cy, half, 1 - half)
    z = zoom * (1 + abs(math.radians(rot)) * 1.2)
    M = cv2.getRotationMatrix2D((cx * W, cy * H), rot, z)
    M[0, 2] += W / 2 - cx * W + shake[0]; M[1, 2] += H / 2 - cy * H + shake[1]
    out = cv2.warpAffine(img, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    bx, by = blur
    if abs(bx) > 1 or abs(by) > 1: out = dir_blur(out, bx, by)
    return out

def dir_blur(img, bx, by):
    n = min(int(max(abs(bx), abs(by))), 120)
    if n < 2: return img
    small = cv2.resize(img, (W // 2, H // 2))
    L = n // 2; k = np.zeros((2 * L + 1, 2 * L + 1), np.float32); m = max(abs(bx), abs(by), 1e-6)
    for i in range(-L, L + 1):
        k[int(round(L + i * by / m)), int(round(L + i * bx / m))] = 1
    k /= k.sum()
    return cv2.resize(cv2.filter2D(small, -1, k), (W, H))

# ---------------------------------------------------------------- text
def font(name, size, var=None):
    """load a font by file name from any standard font folder; falls back to a system sans, then PIL's default"""
    path = find_font(name)
    if path is None:
        path = next((p for p in map(find_font, FALLBACK_FONTS) if p), None)
    if path is None:
        return ImageFont.load_default(size=size)
    f = ImageFont.truetype(path, size)
    if var:
        try: f.set_variation_by_axes(var)
        except Exception: pass
    return f

def text_layer(lines, fnt, fill=(255, 255, 255), stroke=0, stroke_fill=(0, 0, 0), shadow=12,
               box=None, box_pad=(36, 18), box_radius=22, line_gap=0.05, align='center'):
    if isinstance(lines, str): lines = [lines]
    norm = [[(ln, {})] if isinstance(ln, str) else ln for ln in lines]
    asc, desc = fnt.getmetrics(); lh = asc + desc
    widths = []
    for ln in norm:
        widths.append(sum(st.get('font', fnt).getlength(t) + (2 * box_pad[0] if st.get('box') else 0) for t, st in ln))
    pad = 60
    TW = int(max(widths)) + pad * 2; TH = int(len(norm) * lh * (1 + abs(line_gap)) + 2 * box_pad[1]) + pad * 2 + 20
    im = Image.new('RGBA', (TW, TH), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    y = pad
    for ln, w in zip(norm, widths):
        x = (TW - w) / 2 if align == 'center' else pad
        for txt, st in ln:
            f = st.get('font', fnt)
            if st.get('box'):
                tw = f.getlength(txt)
                d.rounded_rectangle([x, y + lh * 0.12 - box_pad[1] * .4, x + tw + 2 * box_pad[0], y + lh * 1.0 + box_pad[1] * .2], box_radius, fill=st['box'])
                x += box_pad[0]
            d.text((x, y), txt, font=f, fill=st.get('fill', fill), stroke_width=st.get('stroke', stroke), stroke_fill=st.get('stroke_fill', stroke_fill))
            x += f.getlength(txt) + (box_pad[0] if st.get('box') else 0)
        y += lh * (1 + line_gap)
    if shadow:
        a = im.split()[3].filter(ImageFilter.GaussianBlur(shadow))
        sh = Image.new('RGBA', im.size, (0, 0, 0, 0)); sh.putalpha(a.point(lambda v: v * 0.55))
        base = Image.new('RGBA', im.size, (0, 0, 0, 0)); base.alpha_composite(sh, (0, 6)); base.alpha_composite(im); im = base
    return im.crop(im.getbbox())

def emoji_layer(ch, size):
    f = ImageFont.truetype(EMOJI, 160)
    im = Image.new('RGBA', (200, 200), (0, 0, 0, 0)); ImageDraw.Draw(im).text((10, 10), ch, font=f, embedded_color=True)
    im = im.crop(im.getbbox()); r = size / im.height
    return im.resize((int(im.width * r), size), Image.LANCZOS)

class Overlay:
    def __init__(s, img, t0, t1, x=.5, y=.3, anim='pop', out='fade', anchor='center', wobble=0, rot=0, slide=0):
        s.img = img if isinstance(img, np.ndarray) else np.array(img)
        s.t0, s.t1, s.x, s.y, s.anim, s.out, s.anchor, s.wobble, s.rot, s.slide = t0, t1, x, y, anim, out, anchor, wobble, rot, slide
    def state(s, t):
        if t < s.t0 or t > s.t1: return None
        a_in = (t - s.t0) / 0.22; a_out = (s.t1 - t) / 0.15
        sc, al, dx, dy, rot = 1., 1., 0., 0., s.rot
        if s.anim == 'pop': sc = 0.35 + 0.65 * back_out(a_in, 2.6); al = clamp(a_in * 2.5)
        elif s.anim == 'slam': sc = 1 + 1.4 * (1 - ease_out(a_in / 0.7)); al = clamp(a_in * 3)
        elif s.anim == 'rise': dy = 80 * (1 - ease_out(a_in)); al = clamp(a_in * 1.6)
        elif s.anim == 'slide': dx = -s.slide * (1 - ease_out(a_in)); al = clamp(a_in * 2)
        elif s.anim == 'fade': al = clamp(a_in)
        if s.wobble: rot += s.wobble * math.sin((t - s.t0) * 5)
        if s.out == 'fade': al *= clamp(a_out)
        return sc, al, dx, dy, rot

def composite(frame, ov, t):
    st = ov.state(t)
    if st is None: return frame
    sc, al, dx, dy, rot = st
    if al <= 0.01: return frame
    img = ov.img
    if abs(sc - 1) > 1e-3 or abs(rot) > 0.05:
        h, w = img.shape[:2]
        M = cv2.getRotationMatrix2D((w / 2, h / 2), rot, sc)
        cos, sin = abs(M[0, 0]), abs(M[0, 1]); nw, nh = int(h * sin + w * cos) + 2, int(h * cos + w * sin) + 2
        M[0, 2] += nw / 2 - w / 2; M[1, 2] += nh / 2 - h / 2
        img = cv2.warpAffine(img, M, (nw, nh), flags=cv2.INTER_LINEAR, borderValue=(0, 0, 0, 0))
    h, w = img.shape[:2]
    cx, cy = ov.x * W + dx, ov.y * H + dy
    if ov.anchor == 'center': x0, y0 = int(cx - w / 2), int(cy - h / 2)
    elif ov.anchor == 'left': x0, y0 = int(cx), int(cy - h / 2)
    else: x0, y0 = int(cx - w), int(cy - h / 2)
    fx0, fy0, fx1, fy1 = max(x0, 0), max(y0, 0), min(x0 + w, W), min(y0 + h, H)
    if fx1 <= fx0 or fy1 <= fy0: return frame
    sub = img[fy0 - y0:fy1 - y0, fx0 - x0:fx1 - x0]
    a = sub[..., 3:4].astype(np.float32) / 255 * al
    rgb = sub[..., :3][..., ::-1].astype(np.float32)
    roi = frame[fy0:fy1, fx0:fx1].astype(np.float32)
    frame[fy0:fy1, fx0:fx1] = (roi * (1 - a) + rgb * a).astype(np.uint8)
    return frame

# ---------------------------------------------------------------- audio synth
from scipy.signal import butter, sosfilt, fftconvolve
_AUDIO = {}
def load_src_audio(src=None):
    src = src or SRC
    if not src: _need_src()
    if src not in _AUDIO:
        p = subprocess.run(['ffmpeg', '-v', 'error', '-i', src, '-ac', '1', '-ar', str(SR), '-f', 'f32le', '-'], capture_output=True)
        a = np.frombuffer(p.stdout, np.float32).astype(np.float64)
        _AUDIO[src] = a if len(a) else np.zeros(SR)
    return _AUDIO[src]
def bandpass(x, lo, hi): return sosfilt(butter(2, [lo, hi], btype='band', fs=SR, output='sos'), x)
def highpass(x, f): return sosfilt(butter(2, f, btype='high', fs=SR, output='sos'), x)
def lowpass(x, f): return sosfilt(butter(2, f, btype='low', fs=SR, output='sos'), x)

rng = np.random.default_rng(7)
def env(n, att, dec):
    t = np.arange(n) / SR; e = np.exp(-t / dec); a = int(att * SR)
    if a > 0: e[:a] *= np.linspace(0, 1, a)
    return e
def kick(dur=0.45, f0=160, f1=45, punch=1.0, dist=1.0):
    n = int(dur * SR); t = np.arange(n) / SR
    f = f1 + (f0 - f1) * np.exp(-t * 28)
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * env(n, .0015, dur / 3.2) + punch * 0.4 * rng.standard_normal(n) * env(n, .0015, .004)  # 1.5 ms attack: real drums never start at full scale
    return np.tanh(x * dist * 1.6) * .9
def snare(dur=0.25):
    n = int(dur * SR); t = np.arange(n) / SR
    return (np.sin(2 * np.pi * 190 * t) * env(n, .001, .05) * .5 + bandpass(rng.standard_normal(n), 1200, 9000) * env(n, .0015, .07) * 1.3) * .6
def clap(dur=0.3):
    n = int(dur * SR); x = np.zeros(n); nz = bandpass(rng.standard_normal(n), 900, 5000)
    for o in [0, .011, .022]:
        i = int(o * SR); x[i:] += nz[i:] * env(n - i, .001, .012 if o < .02 else .12)
    return x * .7
def hat(dur=0.06, open_=False):
    n = int((0.3 if open_ else dur) * SR)
    return highpass(rng.standard_normal(n), 7000) * env(n, .001, .09 if open_ else .015) * .35
def cowbell(dur=0.35, pitch=1.0):
    n = int(dur * SR); t = np.arange(n) / SR
    x = np.sign(np.sin(2 * np.pi * 540 * pitch * t)) + np.sign(np.sin(2 * np.pi * 800 * pitch * t))
    return np.tanh(bandpass(x, 500 * pitch, 2600 * pitch) * env(n, 0, .09) * 1.5) * .35
def bass808(freq, dur, glide_from=None, dist=2.2):
    n = int(dur * SR); t = np.arange(n) / SR
    f = np.full(n, freq) if glide_from is None else freq + (glide_from - freq) * np.exp(-t * 18)
    return np.tanh(np.sin(2 * np.pi * np.cumsum(f) / SR) * env(n, .003, dur * .9) * dist) * .55
def pad_chord(freqs, dur, bright=1800, amp=.12):
    n = int(dur * SR); t = np.arange(n) / SR; x = np.zeros(n)
    for fr in freqs:
        for det in (-0.12, 0.0, 0.11):
            x += (((2 * np.pi * fr * (1 + det / 100 * 6) * t + rng.uniform(0, 6)) / np.pi) % 2 - 1)
    x = lowpass(x / (len(freqs) * 3), bright)
    return x * np.minimum(1, t / 0.08) * np.minimum(1, (dur - t) / 0.12).clip(0, 1) * amp * 3
def pluck(freq, dur=0.35, amp=.18):
    n = int(dur * SR); t = np.arange(n) / SR
    return (np.sin(2 * np.pi * freq * t) + .5 * np.sin(4 * np.pi * freq * t) + .25 * np.sin(6 * np.pi * freq * t)) * env(n, .002, .12) * amp
def bell(freq, dur=1.2, amp=.12):
    n = int(dur * SR); t = np.arange(n) / SR
    return sum(np.sin(2 * np.pi * freq * r * t) * env(n, .001, d) * g for r, d, g in [(1, .6, 1), (2.76, .25, .4), (5.4, .1, .2)]) * amp
def whoosh(dur=0.45, up=True, amp=.5):
    n = int(dur * SR); nz = rng.standard_normal(n); t = np.linspace(0, 1, n)
    lo = 300 + (5000 if up else 300) * (t if up else 1 - t)
    out = np.zeros(n); ch = 1024
    for i in range(0, n, ch):
        f = lo[i]; seg = bandpass(nz[max(0, i - 2048):i + ch], max(80, f * .5), min(18000, f * 2 + 400))
        out[i:i + ch] = seg[-len(out[i:i + ch]):]
    return out * np.sin(np.pi * t) ** 1.5 * amp
def riser(dur=1.5, amp=.35):
    n = int(dur * SR); t = np.arange(n) / SR
    f = 200 * (2 ** (t / dur * 3)); x = np.sin(2 * np.pi * np.cumsum(f) / SR) * .3
    return (x * (t / dur) ** 1.5 + highpass(rng.standard_normal(n), 2000) * (t / dur) ** 2 * .6) * amp
def impact(dur=1.4, amp=.9):
    n = int(dur * SR); k = np.zeros(n); kk = kick(.6, 120, 35, 1.5, 1.4)[:n]; k[:len(kk)] = kk
    return (k + lowpass(rng.standard_normal(n), 1800) * env(n, .003, .35) * .35) * amp
def pop(amp=.35, f0=700, f1=1400):
    n = int(.08 * SR); t = np.arange(n) / SR
    return np.sin(2 * np.pi * np.cumsum(f0 + (f1 - f0) * t / .08) / SR) * env(n, .001, .02) * amp
def swish_ding(amp=.25):
    b2 = np.pad(bell(2093, .9, amp * .8), (int(.07 * SR), SR))[:SR]
    return bell(1568, 1.0, amp)[:SR] + b2
def place(buf, clip, t, gain=1.0):
    i = int(t * SR)
    if i >= len(buf): return
    if i < 0: clip = clip[-i:]; i = 0
    j = min(len(buf), i + len(clip)); buf[i:j] += clip[:j - i] * gain
def reverb(x, wet=.18, dec=1.2):
    n = int(dec * SR); ir = rng.standard_normal(n) * np.exp(-np.arange(n) / SR / (dec / 5))
    ir = lowpass(ir, 5000); ir /= np.abs(ir).sum() ** .5 * 8
    return x + fftconvolve(x, ir)[:len(x)] * wet
def sidechain(x, beats, depth=.55, rel=.18):
    g = np.ones_like(x)
    for b in beats:
        i = int(b * SR); n = int(rel * SR)
        if i >= len(x): continue
        j = min(len(x), i + n); tt = np.arange(j - i) / n
        g[i:j] = np.minimum(g[i:j], 1 - depth * (1 - tt) ** 2)
    return x * g
def duck(x, regions, depth=.6, fade=.08):
    """lower music under voice-over regions [(t0,t1),...]"""
    g = np.ones_like(x)
    for t0, t1 in regions:
        a, b = int((t0 - fade) * SR), int((t1 + fade) * SR)
        a = max(a, 0); b = min(b, len(x))
        if b <= a: continue
        seg = np.full(b - a, 1 - depth); f = int(fade * SR)
        seg[:f] = np.linspace(1, 1 - depth, min(f, len(seg)))[:len(seg[:f])]
        seg[-f:] = np.linspace(1 - depth, 1, f)[-len(seg[-f:]):]
        g[a:b] = np.minimum(g[a:b], seg)
    return x * g
def src_audio_track(tl, src_audio=None, total=None, gain=1.0):
    """varispeed original sound along the timeline (each Seg uses its own footage audio)."""
    total = total or tl.dur
    n = int(total * SR); out = np.zeros(n); ts = np.arange(n) / SR
    for i, g in enumerate(tl.segs):
        src_audio = load_src_audio(g.src)
        a, b = int(tl.starts[i] * SR), int(min(tl.starts[i + 1], total) * SR)
        if b <= a: continue
        s = g.src_time((ts[a:b] - tl.starts[i]) / g.dur) * SR
        seg = np.interp(s, np.arange(len(src_audio)), src_audio)
        fl = min(220, (b - a) // 2); e = np.ones(b - a)
        if i > 0: e[:fl] = np.linspace(0, 1, fl)                      # no fade at the loop seam: the bridge's footage
        if i < len(tl.segs) - 1: e[-fl:] = np.linspace(1, 0, fl)      # sound runs straight into the opening shot's
        out[a:b] = seg * e
    out = highpass(out, 120)
    return out / (np.sqrt((out ** 2).mean()) + 1e-9) * 0.05 * gain
def loop_audio(x, sec):
    """seamless audio loop: drop the first `sec` and crossfade it into the tail (pairs with render(loop_blend=sec))."""
    L = int(sec * SR)
    if L <= 0: return x
    head, body = x[:L].copy(), x[L:].copy()
    f = np.linspace(0, 1, L) ** .5
    body[-L:] = body[-L:] * f[::-1] + head * f
    return body

def loop_fold(x, L, T):
    """loop mix (overlap-add with complementary equal-power windows). Output = x[L:T]; its last L seconds crossfade
    into the head x[:L], exactly like the video's loop_blend. Anything ringing past T belongs to the faded-out side,
    so it is dropped (window = 0), not re-added. Ringing chords don't get cut: music() turns the harmony around so
    the chord fading out at the seam is the same chord fading in, and the sound simply continues."""
    Ls, Ts = int(round(L * SR)), int(round(T * SR))
    body = x[Ls:Ts].copy(); head = x[:Ls]
    if Ls:
        f = np.sin(np.linspace(0, np.pi / 2, Ls)); body[-Ls:] = body[-Ls:] * f[::-1] + head * f
    return body

def limiter(x, ceil=.95):
    x = np.tanh(x * 1.1) / np.tanh(1.1)
    p = np.abs(x).max(); return x / p * ceil if p > ceil else x
def loudnorm_file(src, dst, target=-14.0, tp=-1.5):
    """two-pass EBU R128 normalisation (linear gain, so loops stay seamless). Works on wav or mp4 (video copied)."""
    import json as _j
    r = subprocess.run(['ffmpeg', '-hide_banner', '-i', src, '-af', f'loudnorm=I={target}:TP={tp}:LRA=11:print_format=json', '-f', 'null', '-'], capture_output=True, text=True)
    m = _j.loads(r.stderr[r.stderr.rindex('{'):r.stderr.rindex('}') + 1])
    af = (f"loudnorm=I={target}:TP={tp}:LRA=11:linear=true:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}")
    vid = ['-c:v', 'copy', '-c:a', 'aac', '-b:a', '256k', '-movflags', '+faststart'] if dst.endswith('.mp4') else ['-ar', str(SR)]
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', src, '-af', af] + vid + [dst], check=True)
    return float(m['input_i'])

def lufs(x):
    """integrated loudness (EBU R128) of a mono float signal, measured by ffmpeg"""
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f: p = f.name
    write_wav(p, np.clip(x, -1, 1))
    r = subprocess.run(['ffmpeg', '-hide_banner', '-i', p, '-af', 'ebur128', '-f', 'null', '-'], capture_output=True, text=True)
    os.remove(p)
    import re as _re
    v = _re.findall(r'I:\s+(-?[0-9.]+) LUFS', r.stderr)
    return float(v[-1]) if v else -23.0

def normalize_periodic(x, target=-14.0, ceil=.97):
    """loudness to target with a single linear gain + memoryless soft clip: unlike ffmpeg loudnorm (which can fall back
    to time-varying gain), this keeps a cyclic soundtrack exactly periodic, so the loop seam stays seamless."""
    for _ in range(2):
        x = x * 10 ** ((target - lufs(x)) / 20)
        over = np.abs(x) > ceil * .8
        if over.any(): x = np.where(over, np.sign(x) * (ceil * .8 + (ceil * .2) * np.tanh((np.abs(x) - ceil * .8) / (ceil * .2))), x)
    return x

def write_wav(path, x):
    x = np.clip(x, -1, 1); st = np.stack([x, x], 1)
    with wave.open(path, 'wb') as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes((st * 32767).astype(np.int16).tobytes())
def read_wav(path):
    """mono float at SR (resamples via ffmpeg)"""
    p = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-ac', '1', '-ar', str(SR), '-f', 'f32le', '-'], capture_output=True)
    return np.frombuffer(p.stdout, np.float32).astype(np.float64)

# ---------------------------------------------------------------- render
def _cam(g, u):
    c = g.cam; e = {'io': ease_io, 'out': ease_out, 'in': ease_in, 'lin': lambda x: x}[c['ease']](u)
    return dict(zoom=c['zoom0'] + (c['zoom1'] - c['zoom0']) * e, cx=c['cx0'] + (c['cx1'] - c['cx0']) * e,
                cy=c['cy0'] + (c['cy1'] - c['cy0']) * e, rot=c['rot0'] + (c['rot1'] - c['rot0']) * e)

def run_framegen(plan, src_obj, framegen, smooth_thresh):
    """collect every in-between frame the edit needs and have RIFE generate them (separate env/process)."""
    items, keys = [], set()
    os.makedirs(framegen['dir'], exist_ok=True)
    for (sp_, ft, spd) in plan:
        if spd >= smooth_thresh: continue
        i0 = int(math.floor(ft)); a = round(ft - i0, 4)
        if not (.04 <= a <= .96) or (sp_, i0, a) in keys: continue
        keys.add((sp_, i0, a)); h = hashlib.md5(f'{sp_}|{CROP.get(sp_)}'.encode()).hexdigest()[:8]
        out = os.path.join(framegen['dir'], f'{h}_{i0}_{a:.4f}.jpg')
        items.append({'src': sp_, 'crop': list(CROP.get(sp_, (.5, .5))), 'i0': i0, 'a': a, 'out': out})
        src_obj.gen[(sp_, i0, a)] = out
    if not items: return 0
    req = os.path.join(framegen['dir'], 'request.json'); json.dump({'model': framegen['model'], 'items': items}, open(req, 'w'))
    r = subprocess.run([framegen['py'], os.path.join(os.path.dirname(os.path.abspath(__file__)), 'framegen.py'), req], capture_output=True, text=True)
    print('\n'.join(l for l in r.stdout.splitlines() if 'framegen' in l), flush=True)
    if r.returncode:
        print('framegen FAILED, falling back to optical flow:', r.stderr[-600:]); src_obj.gen.clear()
    return len(items)

def render(tl, out_path, wav_path, overlays, fx=None, grade=None, smooth_thresh=0.7, extra_frame=None, loop_blend=0.0, framegen=None):
    """framegen = {'py': rife env python, 'model': rife model dir, 'dir': cache dir}: every slower-than-realtime frame
    becomes a RIFE-generated in-between frame (true slow motion). Without it, OpenCV DIS flow is used below 0.7x."""
    if framegen: smooth_thresh = 0.999
    """loop_blend>0: the first `loop_blend` s are cross-dissolved into the tail and the video starts after them,
    so the last frame flows into the first (seamless loop). Pair with loop_audio(mix, loop_blend)."""
    total = tl.dur; nf = int(round(total * FPS)); K = nf - int(round((total - loop_blend) * FPS)) if loop_blend else 0
    need = {}; plan = []
    gen_plan = []
    def want(g, u):
        sp_ = g.src or SRC; ft_ = g.src_time(u) * src_fps(sp_); spd = g.speed_at(u)
        i0 = int(math.floor(ft_)); st = need.setdefault(sp_, set()); st.update({i0, i0 + 1})
        if spd >= SHUTTER_FROM: st.update(range(int(round(ft_)) - 5, int(round(ft_)) + 1))
        gen_plan.append((sp_, ft_, spd))
        return sp_, ft_
    for k in range(nf):
        t = k / FPS; i, g, u = tl.at(t)
        sp_, ft = want(g, u)
        if g.split is not None: want(g.split, u)
        plan.append((t, i, g, u, sp_, ft, g.speed_at(u)))
    src = FrameSource(need)
    if framegen: run_framegen(gen_plan, src, framegen, smooth_thresh)
    grade = grade or make_grade()
    tmp = out_path + '.part.mp4'
    proc = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
                             '-i', wav_path, '-c:v', 'libx264', '-preset', 'medium', '-crf', '17', '-pix_fmt', 'yuv420p', '-profile:v', 'high',
                             '-threads', '4', '-c:a', 'aac', '-b:a', '256k', '-shortest', '-movflags', '+faststart', tmp], stdin=subprocess.PIPE)
    head = []
    for k, (t, i, g, u, sp_, ft, sp) in enumerate(plan):
        img = src.interp(sp_, ft, sp < smooth_thresh, sp)
        params = dict(_cam(g, u), shake=(0, 0), blur=(0, 0), flash=0., bright=0.)
        if fx: fx(t, i, g, u, params)
        img = camera(img, params['zoom'], params['cx'], params['cy'], params['rot'], params['shake'], params['blur'])
        if g.split is not None:
            s2 = g.split; ft2 = s2.src_time(u) * src_fps(s2.src or SRC); c2 = _cam(s2, u)
            sp2 = s2.speed_at(u); img2 = camera(src.interp(s2.src or SRC, ft2, sp2 < smooth_thresh, sp2), c2['zoom'], c2['cx'], c2['cy'], c2['rot'])
            if g.split_mode == 'v':
                img = np.vstack([img[H // 4:H // 4 + H // 2], img2[H // 4:H // 4 + H // 2]])
                cv2.rectangle(img, (0, H // 2 - 3), (W, H // 2 + 3), (255, 255, 255), -1)
            else:
                img = np.hstack([img[:, W // 4:W // 4 + W // 2], img2[:, W // 4:W // 4 + W // 2]])
                cv2.rectangle(img, (W // 2 - 3, 0), (W // 2 + 3, H), (255, 255, 255), -1)
            img = np.ascontiguousarray(img)
        img = grade(img)
        if params['bright']: img = cv2.convertScaleAbs(img, alpha=1 + params['bright'], beta=0)
        if params['flash'] > 0: img = cv2.addWeighted(img, 1 - params['flash'], np.full_like(img, 255), params['flash'], 0)
        for ov in overlays: img = composite(img, ov, t)
        if extra_frame: img = extra_frame(img, t)
        if k < K: head.append(img); continue
        if k >= nf - K:
            j = k - (nf - K); a = (j + 1) / (K + 1)
            img = cv2.addWeighted(img, 1 - a, head[j], a, 0)
        proc.stdin.write(img.tobytes())
    proc.stdin.close(); rc = proc.wait()
    if rc == 0: os.replace(tmp, out_path)
    if framegen and not framegen.get('keep'):  # generated frames are per-edit; don't let them pile up on disk
        for pth in set(src.gen.values()):
            try: os.remove(pth)
            except OSError: pass
    return rc
