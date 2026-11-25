#!/usr/bin/env bash
# Creates one GitHub issue per alerts/*.title (→ phone notification), retrying when GitHub's API has a temporary error
# (502/503, timeouts). It never fails the job: if an alert still can't be sent after 5 tries, the alert state is put back
# so the next run sends it again, and the market data is still saved.
set -u
failed=0
for t in alerts/*.title; do
  [ -e "$t" ] || continue
  ok=0
  for i in 1 2 3 4 5; do
    if gh issue create --title "$(cat "$t")" --body-file "${t%.title}.md"; then ok=1; break; fi
    echo "Alert not sent (try $i/5), retrying in $((i * 15)) s"; sleep $((i * 15))
  done
  [ $ok = 1 ] || failed=1
done
rm -rf alerts
if [ $failed = 1 ]; then
  echo "::warning::GitHub refused the alert after 5 tries; the next run will send it again."
  git checkout -- data/alert-state.json 2>/dev/null || true
fi
exit 0
