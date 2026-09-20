#!/bin/bash
# AION CONTROL SYNC — V1
# Deterministic, session-independent sync of canonical control-state to GitHub.
#
# Pipeline (one run):
#   lock → validate → secret scan → visibility check (must be PRIVATE)
#   → git stage → deterministic commit → push (bounded retry) → remote SHA verify
#   → sync log + state (kept OUTSIDE the repo: ~/.aion-control-sync — WatchPaths would re-fire on them)
#   Idle runs (nothing changed) make no writes and at most one ls-remote per 4 min.
#
# Law: NO CRITICAL WORKFLOW STEP MAY DEPEND ON CLAUDE REMEMBERING TO PERFORM IT.
# This script is meant to be run by an OS supervisor (launchd), never by hand
# as the daily mechanism. Running it by hand is allowed only for a self-test.
#
# Exit codes:
#   0 PASS or NOOP     2 VALIDATION_FAILED   3 SECRET_BLOCKER   4 VISIBILITY_NOT_PRIVATE
#   5 PUSH_FAILED      6 REMOTE_MISMATCH     7 LOCKED (another run active)   8 TOOLING_MISSING
set -u
set -o pipefail

REPO_DIR="${AION_CONTROL_DIR:?set AION_CONTROL_DIR=/path/to/your/canon}"
REMOTE_NAME="origin"
BRANCH="main"
GH_REPO="${AION_GH_REPO:?set AION_GH_REPO=owner/repo}"
STATE_DIR="${AION_SYNC_STATE_DIR:-$HOME/.aion-control-sync}"   # OUTSIDE the watched tree (self-retrigger otherwise)
LOG_FILE="$STATE_DIR/sync.log"
STATE_FILE="$STATE_DIR/state.json"
LOCK_DIR="$STATE_DIR/lock.d"
LOCK_STALE_SEC=900
IDLE_RECHECK_SEC="${AION_SYNC_IDLE_RECHECK:-240}"   # idle: verify remote at most every 4 min
DEBOUNCE_SEC="${AION_SYNC_DEBOUNCE:-15}"   # let a writer finish before we look
TRIGGER="${1:-unknown}"                    # launchd | manual | selftest
PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PATH
export GIT_TERMINAL_PROMPT=0
export GIT_HTTP_LOW_SPEED_LIMIT=1000
export GIT_HTTP_LOW_SPEED_TIME=60

TRACKED_FILES=(
  "00-START-HERE.md"
  "01-AION-MASTER.md"
  "02-PRE-PHASE-00-FACTS.md"
  "03-HANDOFF.md"
  "04-LEGACY-FOUNDATIONS-TO-MERGE.md"
  "05-CURRENT-STATE.md"
  "06-PROGRESS-LEDGER.md"
)
# 07-AGENT-TRUST-AND-OPERATING-MODEL.md is picked up automatically when it appears
# (everything not gitignored is staged); it is only REQUIRED once it exists.

mkdir -p "$STATE_DIR"
ts() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }
log() { printf '%s trigger=%s pid=%s %s\n' "$(ts)" "$TRIGGER" "$$" "$*" >> "$LOG_FILE"; }

write_state() {
  # $1 result  $2 local_sha  $3 remote_sha  $4 detail
  local result="$1" lsha="$2" rsha="$3" detail="$4"
  local prev_fail=0 last_pass="" cons=0
  if [ -f "$STATE_FILE" ]; then
    prev_fail=$(sed -n 's/.*"consecutive_failures": *\([0-9]*\).*/\1/p' "$STATE_FILE" | head -1)
    last_pass=$(sed -n 's/.*"last_pass_at": *"\([^"]*\)".*/\1/p' "$STATE_FILE" | head -1)
  fi
  prev_fail=${prev_fail:-0}
  case "$result" in
    PASS|NOOP) cons=0; [ "$result" = "PASS" ] && last_pass="$(ts)";;
    *) cons=$((prev_fail + 1));;
  esac
  cat > "$STATE_FILE.tmp" <<EOF
{
  "last_run_at": "$(ts)",
  "last_trigger": "$TRIGGER",
  "last_result": "$result",
  "last_detail": "$detail",
  "local_head_sha": "$lsha",
  "remote_head_sha": "$rsha",
  "remote_match": $([ -n "$lsha" ] && [ "$lsha" = "$rsha" ] && echo true || echo false),
  "last_pass_at": "$last_pass",
  "last_remote_check_epoch": $([ -n "$rsha" ] && date +%s || echo 0),
  "consecutive_failures": $cons
}
EOF
  mv -f "$STATE_FILE.tmp" "$STATE_FILE"
}

fail() {
  # $1 code  $2 result  $3 detail
  log "RESULT=$2 $3"
  write_state "$2" "$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || echo '')" "" "$3"
  rmdir "$LOCK_DIR" 2>/dev/null
  exit "$1"
}

# ---------- tooling ----------
for t in git gh; do
  command -v "$t" >/dev/null 2>&1 || { log "RESULT=TOOLING_MISSING missing=$t"; exit 8; }
done
[ -d "$REPO_DIR/.git" ] || { log "RESULT=TOOLING_MISSING no .git in $REPO_DIR"; exit 8; }

# ---------- lock (atomic mkdir; stale lock reclaimed after LOCK_STALE_SEC) ----------
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  if [ -d "$LOCK_DIR" ]; then
    age=$(( $(date +%s) - $(stat -f %m "$LOCK_DIR" 2>/dev/null || echo 0) ))
    if [ "$age" -gt "$LOCK_STALE_SEC" ]; then
      log "stale lock age=${age}s reclaimed"
      rmdir "$LOCK_DIR" 2>/dev/null; mkdir "$LOCK_DIR" 2>/dev/null || { log "RESULT=LOCKED"; exit 7; }
    else
      log "RESULT=LOCKED another run active age=${age}s"
      exit 7
    fi
  fi
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null' EXIT

cd "$REPO_DIR" || fail 8 TOOLING_MISSING "cannot cd $REPO_DIR"

# ---------- idle fast-path (WatchPaths also fires on our own .git writes) ----------
# --no-optional-locks: read-only, does not touch .git/index → no re-trigger.
if [ -z "$(git --no-optional-locks status --porcelain 2>/dev/null)" ]; then
  last_check=$(sed -n 's/.*"last_remote_check_epoch": *\([0-9]*\).*/\1/p' "$STATE_FILE" 2>/dev/null | head -1)
  now=$(date +%s)
  if [ -n "$last_check" ] && [ $((now - last_check)) -lt "$IDLE_RECHECK_SEC" ]; then
    rmdir "$LOCK_DIR" 2>/dev/null; trap - EXIT
    exit 0                                   # silent: nothing changed, remote verified recently
  fi
  lsha=$(git rev-parse HEAD)
  rsha=$(git ls-remote "$REMOTE_NAME" "refs/heads/$BRANCH" 2>/dev/null | cut -f1)   # one cheap call, no gh api
  if [ -n "$rsha" ] && [ "$lsha" = "$rsha" ]; then
    log "RESULT=NOOP idle local=$lsha remote=$rsha"
    write_state NOOP "$lsha" "$rsha" "idle, remote verified"
    exit 0
  fi
  log "idle but local=$lsha remote=${rsha:-UNREACHABLE} → full run"
fi

[ "$DEBOUNCE_SEC" -gt 0 ] && sleep "$DEBOUNCE_SEC"

# ---------- validate canonical state ----------
missing=""
for f in "${TRACKED_FILES[@]}"; do [ -f "$f" ] || missing="$missing $f"; done
[ -z "$missing" ] || fail 2 VALIDATION_FAILED "missing:$missing"

last05=$(grep -o 'LAST_EVENT_ID = E-[0-9]*' 05-CURRENT-STATE.md | head -1 | sed 's/.*= //')
last06=$(grep -o '^### E-[0-9]*' 06-PROGRESS-LEDGER.md | tail -1 | sed 's/^### //')
[ -n "$last05" ] && [ -n "$last06" ] || fail 2 VALIDATION_FAILED "event id unreadable 05=$last05 06=$last06"
[ "$last05" = "$last06" ] || fail 2 VALIDATION_FAILED "DOCUMENT_CONFLICT LAST_EVENT_ID 05=$last05 06=$last06"

mv01=$(sed -n 's/^VERSION *= *\(MASTER-[0-9A-Za-z-]*\).*/\1/p' 01-AION-MASTER.md | head -1)
mv05=$(sed -n 's/.*MASTER_VERSION *= *\(MASTER-[0-9A-Za-z-]*\).*/\1/p' 05-CURRENT-STATE.md | head -1)
[ -n "$mv01" ] && [ -n "$mv05" ] || fail 2 VALIDATION_FAILED "master version unreadable 01=$mv01 05=$mv05"
[ "$mv01" = "$mv05" ] || fail 2 VALIDATION_FAILED "DOCUMENT_CONFLICT MASTER_VERSION 01=$mv01 05=$mv05"

# reconcile (L0.11): desired vs actual across documents, processes, runtime, in-flight.
# Any named drift closes publication. git area is skipped there — it is what this script fixes.
recon_out=$(python3 "$REPO_DIR/bin/aionctl" reconcile --dlya-publikacii 2>&1); recon_rc=$?
if [ "$recon_rc" -ne 0 ]; then
  recon_why=$(printf '%s\n' "$recon_out" | grep -E '^\s+- ' | head -3 | sed 's/^ *- //' | tr '\n' ';')
  fail 2 VALIDATION_FAILED "RECONCILE_DRIFT rc=$recon_rc ${recon_why:-$(printf '%s' "$recon_out" | tail -1)}"
fi

# ---------- secret scan (paths + pattern names only; never values) ----------
scan_hits=""
while IFS= read -r p; do
  re="${p%%::*}"; name="${p##*::}"
  hits=$(git ls-files -co --exclude-standard -z | xargs -0 grep -lIE -i -e "$re" 2>/dev/null)
  [ -z "$hits" ] || scan_hits="$scan_hits [$name]:$(echo "$hits" | tr '\n' ',')"
done <<'PATTERNS'
ghp_[A-Za-z0-9]{36}::GITHUB_PAT
github_pat_[A-Za-z0-9_]{20,}::GITHUB_FINE_PAT
gho_[A-Za-z0-9]{36}::GITHUB_OAUTH
(^|[^A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}::OPENAI_STYLE_KEY
AKIA[0-9A-Z]{16}::AWS_ACCESS_KEY
xox[baprs]-[A-Za-z0-9-]{10,}::SLACK_TOKEN
AIza[0-9A-Za-z_-]{35}::GOOGLE_API_KEY
-----BEGIN [A-Z ]*PRIVATE KEY-----::PRIVATE_KEY_BLOCK
eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}::JWT
(password|passwd|api[_-]?key|client[_-]?secret|bearer)[[:space:]]*[:=][[:space:]]*["']?[A-Za-z0-9_./+-]{16,}::KEY_VALUE_ASSIGNMENT
PATTERNS
# sensitive filenames that slipped past .gitignore
badnames=$(git ls-files -co --exclude-standard | grep -iE '(^|/)(\.env(\..*)?|.*\.(pem|key|p12|pfx)|credentials.*|secrets.*|token.*|cookies.*)$')
[ -z "$badnames" ] || scan_hits="$scan_hits [SENSITIVE_FILENAME]:$(echo "$badnames" | tr '\n' ',')"
[ -z "$scan_hits" ] || fail 3 SECRET_BLOCKER "$scan_hits"

# ---------- remote visibility must be PRIVATE (fail closed: unknown != private) ----------
vis=$(gh api "repos/$GH_REPO" --jq '.private' 2>/dev/null)
[ "$vis" = "true" ] || fail 4 VISIBILITY_NOT_PRIVATE "gh_private=${vis:-UNKNOWN}"

# ---------- stage ----------
git add -A >/dev/null 2>&1
if git diff --cached --quiet; then
  lsha=$(git rev-parse HEAD)
  rsha=$(git ls-remote "$REMOTE_NAME" "refs/heads/$BRANCH" 2>/dev/null | cut -f1)
  if [ -n "$rsha" ] && [ "$lsha" = "$rsha" ]; then
    log "RESULT=NOOP nothing to commit local=$lsha remote=$rsha"
    write_state NOOP "$lsha" "$rsha" "nothing to commit"
    exit 0
  fi
  # nothing new locally but remote differs / unreachable → push what we have (may be a previous unpushed commit)
  log "no new changes; local=$lsha remote=${rsha:-UNREACHABLE} → attempting push"
else
  changed=$(git diff --cached --name-only | tr '\n' ' ')
  n=$(git diff --cached --name-only | wc -l | tr -d ' ')
  msg="sync: $(ts) $n file(s): $changed"
  git -c user.name="AION Control Sync" -c user.email="aion-control-sync@local" \
      commit -q -m "$msg" || fail 5 PUSH_FAILED "commit failed"
  log "COMMIT $(git rev-parse --short HEAD) $msg"
fi

# ---------- integrate remote before push (added 2026-09-17) ----------
# BEDA, izmereno 17.09: sync could only push. While only we wrote to main that
# was enough. The moment the Director started writing to main itself, the
# remote moved ahead and push began failing FOREVER: every two minutes a local
# commit plus four rejected attempts. Fifty unpushed commits piled up, the
# Director saw a frozen repository and concluded its tasks never arrive --
# while ingestion was in fact working the whole time.
#
# Fix is the missing half: fetch and MERGE (not rebase -- rebase rewrites
# history and that is what diverged the branches in the first place).
git fetch -q "$REMOTE_NAME" "$BRANCH" >>"$STATE_DIR/push.err" 2>&1 || true
rsha_pre=$(git rev-parse "$REMOTE_NAME/$BRANCH" 2>/dev/null)
if [ -n "$rsha_pre" ] && ! git merge-base --is-ancestor "$rsha_pre" HEAD 2>/dev/null; then
  log "remote ahead ($rsha_pre) -> merging before push"
  if ! git -c user.name="AION Control Sync" -c user.email="aion-control-sync@local" \
        merge -q --no-edit "$REMOTE_NAME/$BRANCH" >>"$STATE_DIR/push.err" 2>&1; then
    conflicts=$(git diff --name-only --diff-filter=U)
    # Guardian snapshots are regenerated every ten seconds -- taking ours loses
    # nothing. ANY other conflict stops the run loudly: silently discarding
    # someone else's change is worse than standing still.
    other=$(printf '%s\n' "$conflicts" | grep -vE '^CHATGPT-DIRECTOR/(GUARDIAN|DEADMAN)-STATUS\.json$' || true)
    if [ -n "$conflicts" ] && [ -z "$other" ]; then
      printf '%s\n' "$conflicts" | while IFS= read -r f; do
        [ -n "$f" ] && git checkout --ours -- "$f" >/dev/null 2>&1 && git add -- "$f" >/dev/null 2>&1
      done
      git -c user.name="AION Control Sync" -c user.email="aion-control-sync@local" \
          commit -q --no-edit >>"$STATE_DIR/push.err" 2>&1 || true
      log "merge: guardian snapshot conflicts resolved with ours"
    else
      git merge --abort >/dev/null 2>&1
      fail 7 MERGE_CONFLICT "$(printf '%s' "$conflicts" | tr '\n' ' ')"
    fi
  fi
fi

# ---------- push with bounded retry/backoff ----------
pushed=0
for delay in 0 10 30 60; do
  [ "$delay" -gt 0 ] && { log "push retry in ${delay}s"; sleep "$delay"; }
  if git push -q "$REMOTE_NAME" "$BRANCH" >>"$STATE_DIR/push.err" 2>&1; then pushed=1; break; fi
done
[ "$pushed" = 1 ] || fail 5 PUSH_FAILED "4 attempts (0/10/30/60s) see .sync/push.err"

# ---------- verify remote == local ----------
lsha=$(git rev-parse HEAD)
rsha=$(git ls-remote "$REMOTE_NAME" "refs/heads/$BRANCH" 2>/dev/null | cut -f1)
[ -n "$rsha" ] && [ "$lsha" = "$rsha" ] || fail 6 REMOTE_MISMATCH "local=$lsha remote=${rsha:-UNREACHABLE}"

log "RESULT=PASS local=$lsha remote=$rsha"
write_state PASS "$lsha" "$rsha" "pushed and verified"
exit 0
