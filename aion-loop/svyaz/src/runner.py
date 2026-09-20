#!/usr/bin/env python3
"""Runner — the hand that calls the director at the right moment.

The loop had one missing piece: after the executor reports through the gate,
somebody has to type `director.py judge`; after the gate writes DONE, somebody
has to type `director.py round`. That somebody was the owner. This is the
somebody now.

It reads the board every tick and does exactly one thing per tick:

    nobody active, items ready        -> director.py round   (dispatch next)
    active item is ACTIVE             -> wait; after NUDGE_MIN one reminder
    active item is PASS_CANDIDATE     -> director.py judge   (three votes)
    judge said no                     -> hand the reasons to the executor once,
                                         wait for a fresh report, judge again
    last item DONE                    -> stop: PROJECT_COMPLETE

It stops — and stays stopped — when the loop cannot go on honestly:
the gate offers nothing, the director or the judge cannot be reached, the
executor has been silent past STALL_MIN, or one item was rejected
MAX_REJECTS times. A frozen board in the morning beats a loop that invents
progress overnight. Every decision goes to the ledger and to state/runner.json.

    python3 runner.py            run until stop
    python3 runner.py --once     one tick, then exit
    python3 runner.py --status   what it would do now, sends nothing
"""
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
CHECKLIST = ROOT / "checklist"
STATE_FILE = CHECKLIST / "sostoyanie.json"
DIRECTOR = HERE / "director.py"
LINK = HERE / "link.py"
LEDGER = ROOT / "svyaz" / "letopis-svyazi.ndjson"
RUNNER_STATE = ROOT / "svyaz" / "state" / "runner.json"
LOG = ROOT / "svyaz" / "state" / "runner.log"
JOURNAL = ROOT / "svyaz" / "state" / "zhurnal-kanala.ndjson"   # observability (N-L1-04): start/end of every move
PAUSE = ROOT / "svyaz" / "state" / "PAUZA"                     # owner's toggle: while this file exists the hand does nothing

TICK_SEC = 20
NUDGE_MIN = 40        # executor working this long -> one reminder
STALL_MIN = 90        # executor silent this long -> stop
REWORK_MIN = 45       # rejected, no fresh report this long -> stop
MAX_REJECTS = 3       # per item
MAX_ATTEMPTS = 3      # per item, counted by the gate


def now():
    return time.time()


def log(text):
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"{stamp} {text}\n")
    print(f"{stamp} {text}", flush=True)


def journal(link, move, phase, **fields):
    """One line per start and per end of a move; failure branches carry `branch`."""
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"t": round(now(), 3), "link": link, "move": move, "phase": phase, **fields},
                                ensure_ascii=False) + "\n")


def record(kind, **fields):
    with LEDGER.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": round(now(), 1), "kind": kind, **fields},
                                ensure_ascii=False) + "\n")


def load_runner():
    if RUNNER_STATE.exists():
        return json.loads(RUNNER_STATE.read_text(encoding="utf-8"))
    return {"stopped": False, "reason": None, "judged": {}, "rejects": {},
            "nudged": [], "rework_since": {}, "started": round(now(), 1)}


def save_runner(state):
    RUNNER_STATE.parent.mkdir(parents=True, exist_ok=True)
    RUNNER_STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1),
                            encoding="utf-8")


def board():
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def run(*args, timeout=1200):
    done = subprocess.run([sys.executable, *args], capture_output=True,
                          text=True, timeout=timeout, cwd=str(HERE))
    return done.returncode, ((done.stdout or "") + (done.stderr or "")).strip()


def tell_executor(text):
    code, said = run(str(LINK), "send", text, timeout=60)
    return code == 0, said[:200]


def stop(state, reason):
    journal("wire", "stop", "end", branch=reason.split(":")[0][:40], reason=reason)
    state["stopped"] = True
    state["reason"] = reason
    save_runner(state)
    record("RUNNER_STOP", reason=reason)
    log(f"STOP: {reason}")


def last_item(spec_board):
    return list(spec_board["пункты"].keys())[-1]


def tick(state, dry=False):
    """One look at the board, one action. Returns False when the loop must stop."""
    # owner's pause (bin/aion-loop off): the hand stays alive but touches nothing —
    # no dispatch, no judge, no message to the window; state on disk is untouched
    if PAUSE.exists():
        if not state.get("paused_logged"):
            log(f"PAUZA владельцем: {PAUSE.read_text(encoding='utf-8').strip()[:120]} — жду «вперёд»")
            record("RUNNER_PAUSED", reason=PAUSE.read_text(encoding="utf-8").strip()[:200])
            state["paused_logged"] = True; save_runner(state)
        return True
    if state.get("paused_logged"):
        log("вперёд: пауза снята, продолжаю с того же места")
        record("RUNNER_RESUMED")
        state["paused_logged"] = False; save_runner(state)
    b = board()
    if b["пункты"][last_item(b)]["state"] == "DONE":
        if not dry:
            stop(state, "PROJECT_COMPLETE")
        return False

    active = b.get("active")
    if not active:
        code, offered = run(str(CHECKLIST / "vorota.py"), "next-ready")
        if code != 0 or not offered.startswith("N-"):
            if not dry:
                stop(state, f"gate offers nothing: {offered[:120]}")
            return False
        if len(b["пункты"][offered]["attempts"]) >= MAX_ATTEMPTS:
            if not dry:
                stop(state, f"{offered}: {MAX_ATTEMPTS} attempts used, owner needed")
            return False
        if dry:
            log(f"would dispatch {offered}")
            return True
        log(f"round -> {offered}")
        t0 = now()
        journal("wire", f"round:{offered}", "start", item=offered)
        code, said = run(str(DIRECTOR), "round", timeout=900)
        log(said[-400:])
        branch = None if code == 0 else ("task_rejected" if "REJECTED:" in said else "director_no_brief" if "no brief" in said else "round_failed")
        journal("wire", f"round:{offered}", "end", item=offered, rc=code, dt=round(now() - t0, 1), branch=branch)
        record("RUNNER_ROUND", item=offered, ok=code == 0)
        if code != 0:
            stop(state, f"director round failed for {offered}: {said[-200:]}")
            return False
        return True

    item = b["пункты"][active]
    attempt = item["attempts"][-1]
    st = item["state"]

    if st == "ACTIVE":
        minutes = (now() - attempt["started_at"]) / 60
        if minutes > STALL_MIN:
            if not dry:
                stop(state, f"{active}: executor silent {minutes:.0f} min")
            return False
        if minutes > NUDGE_MIN and attempt["attempt_id"] not in state["nudged"]:
            if dry:
                log(f"would nudge executor about {active}")
                return True
            journal("wire", f"nudge:{active}", "start", item=active)
            ok, said = tell_executor(
                f"RUNNER: {active} is in work for {minutes:.0f} minutes. "
                f"Report through the gate when you can: "
                f"cd {CHECKLIST} && python3 vorota.py report PASS_CANDIDATE|FAIL|BLOCKED "
                f"--by worker --evidence <file>. If still building, keep going.")
            state["nudged"].append(attempt["attempt_id"])
            save_runner(state)
            journal("wire", f"nudge:{active}", "end", item=active, branch=None if ok else "no_executor_window")
            record("RUNNER_NUDGE", item=active, delivered=ok)
            log(f"nudge {active}: {'delivered' if ok else 'NOT delivered ' + said}")
            if not ok:
                stop(state, f"no executor window: {said}")
                return False
        return True

    if st == "PASS_CANDIDATE":
        key = f"{attempt['attempt_id']}@{attempt.get('finished_at')}"
        if key in state["judged"]:
            since = state["rework_since"].get(active, now())
            if (now() - since) / 60 > REWORK_MIN:
                if not dry:
                    stop(state, f"{active}: rejected, no fresh report in {REWORK_MIN} min")
                return False
            return True
        if dry:
            log(f"would judge {active}")
            return True
        # wire side of the marker dictionary (N-L1-03): once per report, the executor's
        # last words in the window are parsed with the same module the director declares
        # with. The verdict is visible in the log; the gate report stays the source of truth.
        try:
            sys.path.insert(0, str(ROOT / "bin"))
            from markery import parse  # noqa: E402
            code, said = run(str(LINK), "read", "0", timeout=120)
            m = parse(said[-6000:], active)
            log(f"marker {active}: {m['status']} {m.get('marker') or ''} — {m['reason']}")
        except Exception as error:  # noqa: BLE001 - never let marker parsing stop the loop
            log(f"marker {active}: parse error {type(error).__name__}: {error}")
        log(f"judge {active}")
        t0 = now()
        journal("judge", f"judge:{active}", "start", item=active, attempt=attempt["attempt_id"])
        code, said = run(str(DIRECTOR), "judge", timeout=1500)
        log(said[-600:])
        judge_branch = (None if code == 0 else "judge_unavailable" if ("НЕ СОСТОЯЛСЯ" in said or "missing" in said) else "judge_rejected")
        journal("judge", f"judge:{active}", "end", item=active, rc=code, dt=round(now() - t0, 1), branch=judge_branch)
        state["judged"][key] = code
        if code == 0:
            state["rejects"].pop(active, None)
            state["rework_since"].pop(active, None)
            save_runner(state)
            record("RUNNER_JUDGE", item=active, result="PASS")
            # after DONE: the board block in 05 and the registries are rebuilt from disk (plan п.11, NEW-09)
            for tool in ("sobrat-05.py", "sobrat-reestry.py", "sled.py"):
                args = [str(ROOT / "bin" / tool)] + (["sobrat"] if tool == "sled.py" else [])
                rc, out = run(*args, timeout=900)
                log(f"after DONE {tool}: {'ok' if rc == 0 else 'FAIL ' + out[-120:]}")
            return True
        if "НЕ СОСТОЯЛСЯ" in said or "judge interpreter missing" in said:
            stop(state, f"judge unavailable for {active}: {said[-200:]}")
            return False
        n = state["rejects"].get(active, 0) + 1
        state["rejects"][active] = n
        state["rework_since"][active] = round(now(), 1)
        save_runner(state)
        record("RUNNER_JUDGE", item=active, result="REJECTED", n=n)
        if n >= MAX_REJECTS:
            stop(state, f"{active}: rejected {n} times, owner needed")
            return False
        reasons = "\n".join(line for line in said.splitlines()
                            if line.strip().startswith("-"))[:1500]
        journal("wire", f"rework:{active}", "start", item=active, n=n)
        ok, detail = tell_executor(
            f"RUNNER: the judge did not accept {active} (rejection {n} of {MAX_REJECTS}).\n"
            f"Reasons:\n{reasons or said[-800:]}\n\n"
            f"Fix what the reasons name, then report again with evidence:\n"
            f"cd {CHECKLIST} && python3 vorota.py report PASS_CANDIDATE --by worker "
            f"--evidence <file> ...\n"
            f"If it cannot be done honestly, report FAIL or BLOCKED with the reason.")
        journal("wire", f"rework:{active}", "end", item=active, branch=None if ok else "no_executor_window")
        log(f"rework {active}: {'delivered' if ok else 'NOT delivered ' + detail}")
        if not ok:
            stop(state, f"no executor window: {detail}")
            return False
        return True

    # FAIL / BLOCKED leave active empty in the gate; anything else is unknown
    if not dry:
        stop(state, f"{active}: unexpected state {st}")
    return False


def main(argv):
    state = load_runner()
    if "--status" in argv:
        state_copy = json.loads(json.dumps(state))
        log(f"runner stopped={state['stopped']} reason={state['reason']}")
        tick(state_copy, dry=True)
        return 0
    if "--reset" in argv:
        state = {"stopped": False, "reason": None, "judged": {}, "rejects": {},
                 "nudged": [], "rework_since": {}, "started": round(now(), 1)}
        save_runner(state)
        log("runner state reset")
        return 0
    if state["stopped"]:
        log(f"runner is stopped: {state['reason']} (use --reset to clear)")
        return 1
    record("RUNNER_START", once="--once" in argv)
    log("runner start")
    # recovery after restart (N-L1-07): reconcile every task with the registry, deliveries and
    # the queue; continue what is unfinished, never re-dispatch a delivered attempt
    import signal
    from vosstanovlenie import reconcile, journal as rjournal  # noqa: E402
    from mailqueue import Queue  # noqa: E402

    def on_term(signum, frame):
        rjournal("end", event="stop", signal=signum, active=board().get("active"))
        record("RUNNER_STOP", reason=f"signal {signum}")
        log(f"stop by signal {signum}")
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)
    rjournal("start", event="restart")
    rec = reconcile()
    for d in rec["decisions"]:
        log(f"recovery: {d['situation']} {d['task'] or '-'} {d['attempt'] or '-'} -> {d['action']}")
    if any(d["situation"] == "WAITING" for d in rec["decisions"]):
        log(f"recovery: queue drain {Queue().drain()}")
    rjournal("end", event="reconciled", decisions=rec["decisions"], active=rec["active"],
             registry=rec["registry_snapshot"].get(rec["active"] or "", None))
    record("RUNNER_RECOVERY", decisions=[d["situation"] for d in rec["decisions"]], active=rec["active"])
    while True:
        try:
            keep_going = tick(state)
        except Exception as error:  # noqa: BLE001 - the loop must not die silently
            stop(state, f"runner error: {type(error).__name__}: {error}")
            return 1
        if not keep_going:
            return 1
        if "--once" in argv:
            return 0
        time.sleep(TICK_SEC)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
