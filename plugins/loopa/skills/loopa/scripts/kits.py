"""Type kits: six visual languages for on-screen text, so a batch doesn't look like one template stamped
30 times. Copy markup: wrap a word in *asterisks* to accent it.
kit = KITS[name]; kit.headline('nasi goreng *tanpa nasi*'), kit.big('OAT.'), kit.caption(...), kit.chip('01','kol'),
kit.item('jagung', hero=False), kit.label('SEBELUM')"""
import os, re
from engine import font as _font, text_layer, FONTS

def F(name, size):
    """kit fonts are optional: any missing one falls back to a system sans (engine.font handles the search)"""
    return _font(name, size)

def runs(text, accent_style):
    """'ganti pakai *OAT*' -> [('ganti pakai ', {}), ('OAT', accent_style)]"""
    out = []
    for i, part in enumerate(re.split(r'\*([^*]+)\*', text)):
        if part: out.append((part, accent_style if i % 2 else {}))
    return out

def lines(text, accent_style):
    return [runs(ln, accent_style) for ln in text.split('\n')]

MAXW = 960  # keep text inside the frame with side margins

def fit(make, size):
    """render, and if wider than MAXW re-render smaller (no overflow at phone width)"""
    im = make(size)
    if im.width > MAXW:
        im2 = make(max(24, int(size * MAXW / im.width))); im2.info.update(im.info); im = im2
    return im

class Kit:
    def __init__(s, name, head, body, small, accent, fill=(255, 255, 255), stroke=0, shadow=16, box_accent=False, upper=False, dark=(20, 20, 20)):
        s.name, s.head, s.body, s.small, s.accent, s.fill, s.stroke, s.shadow = name, head, body, small, accent, fill, stroke, shadow
        s.box_accent, s.upper, s.dark = box_accent, upper, dark
    def _acc(s):
        return {'box': s.accent, 'fill': s.dark, 'stroke': 0} if s.box_accent else {'fill': s.accent}
    def _t(s, text): return text.upper() if s.upper else text
    def headline(s, text, size=104):
        return fit(lambda z: s._headline(text, z), size)
    def _headline(s, text, size):
        return text_layer(lines(s._t(text), s._acc()), F(s.head, size), fill=s.fill, stroke=s.stroke, shadow=s.shadow, box_pad=(26, 20), line_gap=-.04)
    def big(s, text, size=220):
        return fit(lambda z: s._big(text, z), size)
    def _big(s, text, size):
        return text_layer(lines(s._t(text), s._acc()), F(s.head, size), fill=s.fill, stroke=int(s.stroke * 1.6), shadow=s.shadow + 6, box_pad=(36, 26), line_gap=-.12)
    def caption(s, text, size=72):
        im = fit(lambda z: text_layer(lines(text, {'fill': s.accent}), F(s.body, z), fill=s.fill, stroke=s.stroke, shadow=s.shadow, line_gap=-.03), size)
        im.info['role'] = 'caption'  # dropped automatically in dubbed versions (the voice carries the story)
        return im
    def chip(s, n, label, size=62):
        return text_layer([[(f' {n} ', {'box': s.accent, 'fill': s.dark, 'stroke': 0, 'font': F(s.head, size)}), ('  ' + label, {})]],
                          F(s.body, size), fill=s.fill, stroke=s.stroke, shadow=14, box_pad=(14, 16), box_radius=18)
    def item(s, label, hero=False, size=50):
        st = {'fill': s.accent}
        return text_layer([[('+ ', st), (label, st if hero else {})]], F(s.head if hero else s.body, size + (8 if hero else 0)), fill=s.fill, stroke=max(0, s.stroke - 2), shadow=10)
    def label(s, text, size=58):
        return text_layer([[(f' {text} ', {'box': (0, 0, 0), 'fill': (255, 255, 255), 'stroke': 0})]], F(s.head, size), shadow=0, box_pad=(18, 14), box_radius=12)
    def number(s, text, size=300):
        return text_layer([[(text, {'fill': s.accent})]], F(s.head, size), fill=s.fill, stroke=int(s.stroke * 1.6), shadow=s.shadow + 6)

KITS = {
    'bold':      Kit('bold', 'Poppins-Black.ttf', 'Poppins-ExtraBold.ttf', 'Poppins-SemiBold.ttf', (255, 214, 10), box_accent=True),
    'native':    Kit('native', 'Poppins-Black.ttf', 'Poppins-Bold.ttf', 'Poppins-Bold.ttf', (255, 70, 70), stroke=8, shadow=0),
    'editorial': Kit('editorial', 'Fraunces_72pt_Soft-BlackItalic.ttf', 'Fraunces_72pt_Soft-SemiBoldItalic.ttf', 'Manrope-SemiBold.ttf', (255, 160, 60), fill=(255, 244, 225), shadow=22),
    'minimal':   Kit('minimal', 'Urbanist-ExtraBold.ttf', 'Urbanist-SemiBold.ttf', 'Urbanist-Medium.ttf', (190, 255, 120), shadow=18),
    'rounded':   Kit('rounded', 'Rubik-Black.ttf', 'Rubik-Bold.ttf', 'Rubik-Medium.ttf', (255, 120, 190), box_accent=True, dark=(30, 10, 25)),
    'grotesk':   Kit('grotesk', 'Manrope-ExtraBold.ttf', 'Manrope-Bold.ttf', 'Manrope-SemiBold.ttf', (255, 140, 0), upper=True, shadow=18),
}
