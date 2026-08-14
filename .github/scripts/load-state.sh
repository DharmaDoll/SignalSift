#!/usr/bin/env bash

set -Eeuo pipefail

: "${STATE_BRANCH:?STATE_BRANCH is required}"
: "${RUNNER_TEMP:?RUNNER_TEMP is required}"
: "${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"

mkdir -p .local/state
echo "state_branch=${STATE_BRANCH} simulated_delivery=${SIMULATE_DELIVERY:-false}"

state_probe=0
git ls-remote --exit-code --heads origin "$STATE_BRANCH" >/dev/null || state_probe=$?
if [ "$state_probe" -eq 0 ]; then
  git fetch origin "$STATE_BRANCH:refs/remotes/origin/$STATE_BRANCH"
  echo "branch_exists=true" >> "$GITHUB_OUTPUT"
elif [ "$state_probe" -eq 2 ]; then
  echo "branch_exists=false" >> "$GITHUB_OUTPUT"
else
  echo "cannot inspect origin/$STATE_BRANCH (git status $state_probe)" >&2
  exit 1
fi

for state_file in supply_chain_vulnerability ai_security; do
  remote_path="origin/$STATE_BRANCH:state/${state_file}.json"
  temporary_path="$RUNNER_TEMP/${state_file}.json"
  local_path=".local/state/${state_file}.json"
  if git show "$remote_path" > "$temporary_path" 2>/dev/null; then
    mv "$temporary_path" "$local_path"
  fi
done
