"""Indonesian TTS with Kokoro-82M: espeak-ng (id) -> IPA phonemes -> Kokoro acoustic model.
Kokoro has no official Indonesian; we bypass its English/other G2P and feed Indonesian IPA directly.
usage: python tts_id.py VOICE SPEED OUT.wav "text" """
import sys, os, re, types, subprocess, glob
import numpy as np, torch, soundfile as sf

# load kokoro.model without running kokoro/__init__ (which pulls the English G2P stack)
_site = glob.glob(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(sys.executable))), 'lib', 'python3*', 'site-packages', 'kokoro'))[0]
_pkg = types.ModuleType('kokoro'); _pkg.__path__ = [_site]; sys.modules['kokoro'] = _pkg
import warnings; warnings.filterwarnings('ignore')
from loguru import logger; logger.remove(); logger.add(sys.stderr, level='WARNING')  # kokoro logs every phoneme at DEBUG
from kokoro.model import KModel
from huggingface_hub import hf_hub_download

REPO = 'hexgrad/Kokoro-82M'
_model = None
def model():
    global _model
    if _model is None:
        _model = KModel(repo_id=REPO).eval()
    return _model

def voice(name):
    return torch.load(hf_hub_download(REPO, f'voices/{name}.pt'), weights_only=True)

def ipa(text):
    """espeak-ng Indonesian IPA, keeping punctuation as pause markers."""
    parts = re.split(r'([,.!?…;:])', text)
    out = []
    for p in parts:
        if not p.strip(): continue
        if re.fullmatch(r'[,.!?…;:]', p):
            out.append({'…': '…'}.get(p, p)); continue
        r = subprocess.run(['espeak-ng', '-v', 'id', '-q', '--ipa', p], capture_output=True, text=True).stdout
        r = ' '.join(r.split()).replace('_', '')
        out.append(' ' + r.strip())
    s = ''.join(out).strip()
    vocab = model().vocab
    return ''.join(c for c in s if c in vocab)

def synth(text, voice_name='if_sara', speed=1.0):
    ps = ipa(text)
    pack = voice(voice_name)
    with torch.no_grad():
        audio = model()(ps, pack[len(ps) - 1], speed)
    return audio.numpy(), ps

if __name__ == '__main__':
    v, sp, out, text = sys.argv[1], float(sys.argv[2]), sys.argv[3], sys.argv[4]
    a, ps = synth(text, v, sp)
    sf.write(out, a, 24000)
    print(ps)
