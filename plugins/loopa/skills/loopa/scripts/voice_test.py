"""Pick the most intelligible Kokoro voice for Indonesian: synth one sentence per voice,
transcribe with Whisper (language=id), score word overlap with the script.
usage: ENV/bin/python voice_test.py OUTDIR "kalimat uji" [voice ...]"""
import sys, os, re, difflib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import soundfile as sf
from tts_id import synth
from faster_whisper import WhisperModel

out, text = sys.argv[1], sys.argv[2]
voices = sys.argv[3:] or ['ef_dora', 'em_alex', 'pf_dora', 'pm_alex', 'if_sara', 'im_nicola', 'af_heart']
os.makedirs(out, exist_ok=True)
wm = WhisperModel('small', device='cpu', compute_type='int8')
ref = re.sub(r'[^a-z ]', '', text.lower()).split()
rows = []
for v in voices:
    a, _ = synth(text, v, 1.0); p = os.path.join(out, f'{v}.wav'); sf.write(p, a, 24000)
    hyp = ' '.join(s.text for s in wm.transcribe(p, language='id', beam_size=5)[0])
    score = difflib.SequenceMatcher(None, ref, re.sub(r'[^a-z ]', '', hyp.lower()).split()).ratio()
    rows.append((score, v, hyp.strip()))
for score, v, hyp in sorted(rows, reverse=True):
    print(f'{v:10s} {score:.2f} | {hyp}')
