#!/usr/bin/env bash
# Install the loopa skill for Claude Code (and any agent that reads ~/.claude/skills).
#
#   ./install.sh                         from a clone
#   curl -fsSL <raw-url> | bash          from anywhere (clones itself)
#   curl -fsSL <raw-url> | bash -s -- --all
#
# Options:
#   --project      install into ./.claude/skills of the current directory instead of ~/.claude/skills
#   --deps         create ~/.loopa/venv with the Python packages the renderer needs (opencv, numpy, scipy, pillow)
#   --with-rife    set up AI slow motion (RIFE frame generation, ~/.loopa/rife, ~22 MB of models)
#   --with-tts     set up Indonesian voice-over (Kokoro + faster-whisper, ~/.loopa/tts; models download on first use)
#   --all          --deps --with-rife --with-tts
#
# Claude Code users may prefer the plugin route instead, which handles updates:
#   /plugin marketplace add aldhosutra/loopa
#   /plugin install loopa@aldhosutra
set -euo pipefail

REPO_URL="https://github.com/aldhosutra/loopa.git"
SKILL_SUBPATH="plugins/loopa/skills/loopa"
SCOPE="user"; DEPS=0; RIFE=0; TTS=0
for a in "$@"; do
  case "$a" in
    --project) SCOPE="project" ;;
    --deps) DEPS=1 ;;
    --with-rife) RIFE=1 ;;
    --with-tts) TTS=1 ;;
    --all) DEPS=1; RIFE=1; TTS=1 ;;
    -h|--help) sed -n '2,18p' "$0" 2>/dev/null | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done

for tool in git python3 ffmpeg; do
  command -v "$tool" >/dev/null 2>&1 || echo "warning: $tool not found — loopa needs it (macOS: brew install $tool)" >&2
done

# Work out where the skill is coming from. When piped through bash there is no script on disk, so fetch a copy.
ROOT=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
  HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  [ -d "$HERE/$SKILL_SUBPATH" ] && ROOT="$HERE"
fi
CLONE=""
if [ -z "$ROOT" ]; then
  CLONE="$(mktemp -d)"
  trap 'rm -rf "$CLONE"' EXIT
  echo "fetching $REPO_URL"
  git clone --depth 1 -q "$REPO_URL" "$CLONE/loopa"
  ROOT="$CLONE/loopa"
fi
SRC="$ROOT/$SKILL_SUBPATH"
[ -f "$SRC/SKILL.md" ] || { echo "cannot find the skill at $SRC" >&2; exit 1; }

if [ "$SCOPE" = "project" ]; then DEST="$PWD/.claude/skills/loopa"; else DEST="$HOME/.claude/skills/loopa"; fi
mkdir -p "$(dirname "$DEST")"
if [ -e "$DEST" ] || [ -L "$DEST" ]; then echo "replacing the existing install at $DEST"; rm -rf "$DEST"; fi
cp -R "$SRC" "$DEST"
chmod +x "$DEST/scripts/loopa" "$DEST"/scripts/*.sh "$DEST"/scripts/*.py 2>/dev/null || true
echo "installed the skill to $DEST"

if [ "$DEPS" = 1 ]; then
  echo "creating ~/.loopa/venv (renderer packages)"
  [ -x "$HOME/.loopa/venv/bin/python" ] || python3 -m venv "$HOME/.loopa/venv"
  "$HOME/.loopa/venv/bin/pip" install -q --disable-pip-version-check --upgrade pip >/dev/null 2>&1 || true
  "$HOME/.loopa/venv/bin/pip" install -q --disable-pip-version-check opencv-python-headless numpy scipy pillow
fi
[ "$RIFE" = 1 ] && { echo "setting up AI slow motion (RIFE)"; bash "$DEST/scripts/setup_rife.sh" "$HOME/.loopa/rife"; }
[ "$TTS" = 1 ] && { echo "setting up voice-over (Kokoro TTS)"; bash "$DEST/scripts/setup_tts.sh" "$HOME/.loopa/tts"; }

echo
"$DEST/scripts/loopa" doctor || true
echo
echo "Start a new Claude Code session and ask, for example:"
echo "  \"loopa this folder: ~/Videos/raw — make as many looping shorts as you can\""
