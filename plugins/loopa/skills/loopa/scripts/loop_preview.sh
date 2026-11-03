#!/usr/bin/env bash
# Gapless loop preview: decodes VIDEO N times back-to-back into ONE file, so every seam is inside the file.
# Any player (VLC, QuickTime, phone gallery) then shows the loop exactly as a gapless platform player would.
# (Player "repeat" modes reopen/seek the file and add a 0.1-0.3 s hitch to every video, which says nothing about the edit.)
# usage: loop_preview.sh VIDEO [N=3] [OUT]
set -euo pipefail
V=$1; N=${2:-3}; OUT=${3:-${V%.*}_LOOPx${N}.mp4}
ffmpeg -v error -y -stream_loop $((N - 1)) -i "$V" -c:v libx264 -preset fast -crf 18 -pix_fmt yuv420p -c:a aac -b:a 256k -ar 48000 -movflags +faststart "$OUT"
echo "$OUT  ($(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT" | cut -c1-6)s = ${N} plays)"
