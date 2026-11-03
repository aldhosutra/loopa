#!/usr/bin/env bash
# Indonesian voice-over: Kokoro-82M fed with espeak-ng IPA, plus faster-whisper to check what was actually heard.
# Creates a self-contained venv. Installs only Kokoro's model code (not its English G2P stack: spacy etc.).
# usage: setup_tts.sh [ENV_DIR=~/.loopa/tts]      (auto-detected there by build.py; or set "tts_python" in a plan)
# Downloads on first use: Kokoro model (~330 MB) and whisper-small (~460 MB) into the Hugging Face cache.
set -euo pipefail
ENV=${1:-$HOME/.loopa/tts}
command -v espeak-ng >/dev/null || { echo "espeak-ng missing: brew install espeak-ng  (or apt install espeak-ng)"; exit 1; }
[ -x "$ENV/bin/python" ] || python3 -m venv "$ENV"
PIP="$ENV/bin/pip install -q --disable-pip-version-check"
$PIP --upgrade pip >/dev/null 2>&1 || true
"$ENV/bin/python" -c "import torch, transformers, faster_whisper, soundfile, huggingface_hub, numpy, scipy" 2>/dev/null \
  || $PIP torch transformers faster-whisper soundfile huggingface_hub numpy scipy
$PIP --no-deps kokoro misaki
$PIP loguru addict
"$ENV/bin/python" - <<'PY'
import torch, faster_whisper, soundfile
print('torch', torch.__version__, '| faster-whisper ok')
PY
echo "ready: $ENV/bin/python"
