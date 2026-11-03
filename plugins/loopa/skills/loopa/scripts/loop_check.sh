#!/usr/bin/env bash
# Loop seam QC (video + audio): last 4 | first 4 frames side by side with a seam score, and an audio seam check
# (click, level jump, spectral jump between the end of the file and its start).
# usage: loop_check.sh VIDEO OUT.jpg
set -euo pipefail
V=$1; OUT=$2; T=$(mktemp -d)
N=$(ffprobe -v error -count_packets -select_streams v:0 -show_entries stream=nb_read_packets -of csv=p=0 "$V")
ffmpeg -v error -i "$V" -vf "select='gte(n\,$((N-4)))',scale=180:-1" -vsync 0 "$T/a%d.png"
ffmpeg -v error -i "$V" -vf "select='lt(n\,4)',scale=180:-1" -vsync 0 "$T/b%d.png"
ffmpeg -v error -y -i "$T/a1.png" -i "$T/a2.png" -i "$T/a3.png" -i "$T/a4.png" -i "$T/b1.png" -i "$T/b2.png" -i "$T/b3.png" -i "$T/b4.png" \
  -filter_complex "[0][1][2][3]hstack=4[x];[4][5][6][7]hstack=4[y];[x][y]hstack=2" "$OUT"
python3 - "$T" <<'PY'
import sys, numpy as np
from PIL import Image
d = sys.argv[1]; f = lambda n: np.asarray(Image.open(f'{d}/{n}.png').convert('L'), np.float32)
seam = np.abs(f('a4') - f('b1')).mean(); inner = np.mean([np.abs(f(f'b{i}') - f(f'b{i+1}')).mean() for i in (1, 2, 3)])
print(f'seam diff {seam:.1f} vs normal frame-to-frame {inner:.1f}  ->  ' + ('OK seamless' if seam <= max(6, inner * 2.5) else 'VISIBLE JUMP'))
PY
# audio seam: replay = end of file followed by its start
ffmpeg -v error -i "$V" -ac 1 -ar 44100 -f s16le "$T/a.raw"
python3 - "$T/a.raw" <<'PY'
import sys, numpy as np
x = np.fromfile(sys.argv[1], np.int16).astype(np.float32) / 32768
w = 882                                                    # 20 ms analysis windows
loop = np.concatenate([x, x[:int(.5 * 44100)]])          # the file followed by its own start = what a replay sounds like
J = len(x) // w                                           # window index of the seam
win = lambda i: loop[i * w:(i + 1) * w]
spec = [np.abs(np.fft.rfft(win(i) * np.hanning(w))) for i in range(len(loop) // w)]
flux = np.array([np.sum(np.maximum(spec[i] - spec[i - 1], 0)) for i in range(1, len(spec))])
lev = np.array([20 * np.log10(np.sqrt(np.mean(win(i) ** 2)) + 1e-9) for i in range(len(loop) // w)])
dlev = np.abs(np.diff(lev))
seam_flux = flux[J - 2:J + 1].max(); seam_dlev = dlev[J - 2:J + 1].max()
inner_flux = flux[:J - 3].max(); inner_dlev = dlev[:J - 3].max()   # strongest transition the track already contains
jump = abs(float(x[-1]) - float(x[0])); typ = np.median(np.abs(np.diff(x))) + 1e-6
ok = seam_flux <= 1.1 * inner_flux and seam_dlev <= inner_dlev + 1 and jump < max(8 * typ, .02)
print(f'audio seam: spectral change {seam_flux / inner_flux:.2f}x of track max, level change {seam_dlev:.1f} dB (track max {inner_dlev:.1f} dB), '
      f'click {jump / typ:.1f}x  ->  ' + ('OK smooth (no harsher than transitions already in the track)' if ok else 'AUDIBLE SEAM'))
PY
rm -rf "$T"
