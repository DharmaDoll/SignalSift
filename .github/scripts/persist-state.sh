#!/usr/bin/env bash

set -Eeuo pipefail

: "${STATE_BRANCH:?STATE_BRANCH is required}"
: "${STATE_BRANCH_EXISTS:?STATE_BRANCH_EXISTS is required}"
: "${RUNNER_TEMP:?RUNNER_TEMP is required}"

snapshot_dir="$RUNNER_TEMP/signalsift-state"
mkdir -p "$snapshot_dir"
for state_path in .local/state/*.json; do
  if [ -f "$state_path" ]; then
    cp "$state_path" "$snapshot_dir/"
  fi
done

if [ "$STATE_BRANCH_EXISTS" = "true" ]; then
  git checkout -B "$STATE_BRANCH" "origin/$STATE_BRANCH"
else
  git checkout --orphan "$STATE_BRANCH"
  git rm -rf .
fi

mkdir -p state
for state_path in "$snapshot_dir"/*.json; do
  if [ -f "$state_path" ]; then
    cp "$state_path" state/
  fi
done

git add state
if ! git diff --cached --quiet; then
  git -c user.name="github-actions[bot]" \
    -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
    commit -m "chore: persist SignalSift ${STATE_BRANCH} notification state"
  git push origin "$STATE_BRANCH"
fi
