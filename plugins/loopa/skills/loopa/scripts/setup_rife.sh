#!/usr/bin/env bash
# AI frame generation for true slow motion: RIFE v4.26 via ncnn/Vulkan (runs on the GPU, incl. Apple Silicon).
# Creates a self-contained venv with what framegen.py needs, and downloads the RIFE models (~22 MB).
# usage: setup_rife.sh [ENV_DIR=~/.loopa/rife]      (auto-detected there by build.py; or set "rife_python" in a plan)
set -euo pipefail
ENV=${1:-$HOME/.loopa/rife}
[ -x "$ENV/bin/python" ] || python3 -m venv "$ENV"
PIP="$ENV/bin/pip install -q --disable-pip-version-check"
$PIP --upgrade pip >/dev/null 2>&1 || true
"$ENV/bin/python" -c "import numpy, cv2, scipy, PIL" 2>/dev/null || $PIP numpy opencv-python-headless scipy pillow
$PIP rife-ncnn-vulkan-python-tntwise
for v in rife-v4.26 rife-v4.6; do            # 4.26 = best quality; 4.6 = faster, most battle-tested
  mkdir -p "$ENV/rife-models/$v"
  for f in flownet.param flownet.bin; do
    [ -s "$ENV/rife-models/$v/$f" ] || curl -sfL -o "$ENV/rife-models/$v/$f" "https://raw.githubusercontent.com/TNTwise/rife-ncnn-vulkan/master/models/$v/$f"
  done
done
"$ENV/bin/python" -c "from rife_ncnn_vulkan_python import Rife; Rife(gpuid=0, model='$ENV/rife-models/rife-v4.26'); print('RIFE ok (GPU)')"
echo "ready: $ENV/bin/python"
