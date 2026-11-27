#!/usr/bin/env bash
# Phone alert when a scheduled job fails or hits its time limit (27 Nov 2026): opens one GitHub issue per job per day (Paris
# date), which the GitHub app pushes to the phone. A second failure of the same job on the same day adds nothing (the backup
# runs often fail for the same reason). Never fails the job itself. Usage: bash scripts/job-failed.sh "Market fear"
set -u
name="${1:-StockGlass job}"; day=$(TZ=Europe/Paris date +%F)
title="Job failed: $name ($day)"
run="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-}/actions/runs/${GITHUB_RUN_ID:-}"
if gh issue list --state all --limit 30 --search "in:title \"$title\"" --json title --jq '.[].title' 2>/dev/null | grep -qxF "$title"; then
  echo "Already reported today: $title"; exit 0
fi
body="**$name** did not finish (run started $(TZ=Europe/Paris date '+%a %d %b %H:%M') Paris).

- Run log: $run
- The page keeps showing the last saved data, with its date. The next scheduled run tries again; nothing to do unless this repeats.
- Close this issue once a later run has worked.

Rule-based screen on public data, not investment advice.

@wassim96-dot"
for i in 1 2 3; do
  if gh issue create --title "$title" --body "$body"; then exit 0; fi
  echo "Alert not sent (try $i/3), retrying in $((i * 15)) s"; sleep $((i * 15))
done
echo "::warning::could not open the failure issue"
exit 0
