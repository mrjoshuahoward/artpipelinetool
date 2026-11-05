#!/bin/bash
# Gives the run a read-only snapshot of the Sorting Line repo at ~/developer/sortingline.
# The eval sandbox gives each run its own HOME and denies reads of the real repo, so we copy
# tracked + untracked-but-not-ignored files (no node_modules, ios build, playtest captures) and .git.
set -euo pipefail
SRC="${EVAL_SORTINGLINE_SRC:-/Users/joshuahoward/developer/sortingline}"
DST="$HOME/developer/sortingline"
mkdir -p "$DST"
git -C "$SRC" ls-files -z --cached --others --exclude-standard | rsync -a --from0 --files-from=- "$SRC/" "$DST/"
rsync -a "$SRC/.git" "$DST/"
