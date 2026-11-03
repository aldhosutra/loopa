#!/usr/bin/env bash
# Contact sheet for reviewing footage or a finished render.
# usage: contact_sheet.sh VIDEO OUT.jpg [FPS=1] [COLS=10] [START=0] [DURATION=all] [THUMB_W=180]
set -euo pipefail
V=$1; OUT=$2; FPS=${3:-1}; COLS=${4:-10}; START=${5:-0}; DUR=${6:-}; TW=${7:-180}
LEN=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$V")
[ -z "$DUR" ] && DUR=$(python3 -c "print(max(0.1, $LEN - $START))")
N=$(python3 -c "import math; print(max(1, math.ceil($DUR * $FPS)))")
ROWS=$(python3 -c "import math; print(math.ceil($N / $COLS))")
ffmpeg -v error -y -ss "$START" -t "$DUR" -i "$V" -vf "fps=$FPS,scale=$TW:-1,tile=${COLS}x${ROWS}" -frames:v 1 "$OUT"
echo "$OUT  ($N frames, ${COLS}x${ROWS}, start=$START dur=$DUR)"
