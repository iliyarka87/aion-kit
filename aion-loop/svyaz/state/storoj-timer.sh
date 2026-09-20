#!/bin/bash
# Timer for the watchman: one armed tick per minute. Stops when state/watchman.json says stopped.
# Observability (N-L1-04): every tick is a move with start and end in state/zhurnal-kanala.ndjson.
cd "$(dirname "$0")/.." || exit 1
J=state/zhurnal-kanala.ndjson
n=0
while true; do
  n=$((n+1))
  t0=$(python3 -c 'import time; print(round(time.time(),3))')
  printf '{"t": %s, "link": "wake", "move": "tick:%d", "phase": "start"}\n' "$t0" "$n" >> "$J"
  python3 src/watchman.py tick --arm >> state/watchman-ticks.log 2>&1
  rc=$?
  t1=$(python3 -c 'import time; print(round(time.time(),3))')
  br=$([ "$rc" -eq 0 ] && echo null || echo '"tick_failed"')
  printf '{"t": %s, "link": "wake", "move": "tick:%d", "phase": "end", "rc": %d, "dt": %s, "branch": %s}\n' "$t1" "$n" "$rc" "$(python3 -c "print(round($t1-$t0,3))")" "$br" >> "$J"
  grep -q '"stopped": true' state/watchman.json 2>/dev/null && { echo "$(date -u +%FT%TZ) watchman stopped — timer exits" >> state/watchman-ticks.log; exit 0; }
  sleep 60
done
