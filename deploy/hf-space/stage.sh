#!/usr/bin/env bash
# Copy what the demo Space needs into a folder laid out as a Hugging Face Space repository:
# the checkout's tracked and new files (without docs, tests, research and UI sources), with the
# Dockerfile and the Space card at the root.  Usage: deploy/hf-space/stage.sh <empty output folder>
set -euo pipefail
out=${1:?usage: stage.sh <empty output folder>}
root=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
mkdir -p "$out"
[ -z "$(ls -A "$out")" ] || { echo "$out is not empty" >&2; exit 1; }

cd "$root"
git ls-files -co --exclude-standard -z \
  | grep -zv -E '^(docs|tests|research|ui|examples|\.claude|\.github)/|^(AGENTS|CLAUDE)\.md$' \
  | tar --null -T - -cf - | tar -xf - -C "$out"

cp deploy/hf-space/Dockerfile "$out/Dockerfile"
cp deploy/hf-space/SPACE_README.md "$out/README.md"
# The Space card replaces README.md; keep the project README beside it.
cp README.md "$out/PROJECT_README.md"
du -sh "$out"
