#!/bin/bash
# (Identical copy in every case folder: the runner resolves scaffold_script inside the case.)
# Gives each eval run a read-only copy of Sorting Line, the game the evals use as a test subject,
# at ~/developer/sortingline inside the run's sandbox HOME.
#
# Sorting Line is private and isn't vendored here. The copy comes from a local clone, pinned to the
# commit the recorded results used, so results don't drift as the game changes:
#   EVAL_SORTINGLINE_SRC  path to a Sorting Line clone (default: ~/developer/sortingline in your
#                         real home; each run's sandbox HOME is different)
#   EVAL_SORTINGLINE_REF  commit to use (default: the pinned one below)
set -euo pipefail
PINNED=06ba6cb  # 2026-11-04, Sorting Line HEAD during the Nov 2026 eval runs
REAL_HOME=$(eval echo "~$(id -un)")  # the account's home from the user database, not the sandbox $HOME
SRC="${EVAL_SORTINGLINE_SRC:-$REAL_HOME/developer/sortingline}"
REF="${EVAL_SORTINGLINE_REF:-$PINNED}"
DST="$HOME/developer/sortingline"

if ! git -C "$SRC" rev-parse --verify -q "$REF^{commit}" >/dev/null; then
  echo "scaffold: no Sorting Line commit $REF at $SRC; set EVAL_SORTINGLINE_SRC to a clone that has it" >&2
  exit 1
fi
rm -rf "$DST"
mkdir -p "$DST"
git -C "$SRC" archive --format=tar "$REF" | tar -x -C "$DST"
# A fresh one-commit repo, so the agent (and graders) can see that nothing changed.
git -C "$DST" init -q
git -C "$DST" add -A
git -C "$DST" -c user.name=eval -c user.email=eval@localhost commit -qm "Sorting Line @ $REF (eval snapshot)"
