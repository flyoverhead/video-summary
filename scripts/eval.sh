#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
mkdir -p "$root/.eval-out"
cases=$(find "$root/video-summary/evals" -name prompt.md -not -path '*/results/*' | wc -l | tr -d ' ')
echo "video-summary: $cases cases, ~$((cases * 3 * 2)) agent runs"
claude plugin eval "$root/video-summary" --ablation with-without --trust-plugin --scaffold -j 2 \
  --model "${EVAL_MODEL:-sonnet}" --allow-tools Bash --no-publish --threshold 0 \
  --json "$root/.eval-out/new.json" "$@"
gate=${EVAL_GATE:-}
if [ -n "$gate" ] && [ -f "$gate" ]; then
  python3 "$gate" "$root/.eval-out/new.json"
else
  echo "eval gate skipped (set EVAL_GATE to a gate script)"
fi
