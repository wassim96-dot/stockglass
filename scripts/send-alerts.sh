#!/usr/bin/env bash
# Creates one GitHub issue per alerts/*.title (→ phone notification) and closes the older open alert of the same kind, retrying when GitHub's API has a temporary error
# (502/503, timeouts). It never fails the job: if an alert still can't be sent after 5 tries, the alert state is put back
# so the next run sends it again, and the market data is still saved.
set -u
failed=0
# One open alert per kind (28 Nov 2026): the kind is the title up to the first ":" ("Fear alert", "Minervini", "BTC cycle"...).
# After a new alert is opened, older open issues of the same kind are closed with a pointer to the new one, so the list on
# the phone shows only the latest state. "Job failed" issues are left alone (they are closed by hand once a run works).
supersede() {
  local kind="${1%%:*}" new="$2"
  [ -n "$new" ] && [ "$kind" != "$1" ] && [ "$kind" != "Job failed" ] || return 0
  gh issue list --state open --limit 50 --json number,title --jq ".[] | select(.title | startswith(\"$kind:\")) | select(.number != $new) | .number" 2>/dev/null |
    while read -r n; do gh issue close "$n" --comment "Superseded by #$new." >/dev/null 2>&1 && echo "closed #$n (superseded by #$new)"; done
  return 0
}
for t in alerts/*.title; do
  [ -e "$t" ] || continue
  ok=0
  for i in 1 2 3 4 5; do
    if url=$(gh issue create --title "$(cat "$t")" --body-file "${t%.title}.md"); then ok=1; echo "$url"; supersede "$(cat "$t")" "${url##*/}"; break; fi
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
