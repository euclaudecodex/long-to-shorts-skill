#!/usr/bin/env bash
# Installs the long-to-shorts skill for Claude Code and, if present, Codex (macOS / Linux). Usage: bash install.sh
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
TARGETS=("$HOME/.claude/skills/long-to-shorts")
[ -d "$HOME/.codex" ] && TARGETS+=("$HOME/.codex/skills/long-to-shorts")
for T in "${TARGETS[@]}"; do
  mkdir -p "$T"
  cp -R "$HERE/skills/long-to-shorts/." "$T/"
  echo "Installed to $T"
done
echo
echo "Done! Open Claude and say: clip this video: ~/Videos/stream.mp4  (ou: corta esse vídeo)"
