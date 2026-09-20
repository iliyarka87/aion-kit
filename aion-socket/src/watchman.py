#!/usr/bin/env python3
"""AION Watchman — one command: find both agents, watch both, nudge one.

Eyes and hand in the same tool, because from the outside it is one job. The
eyes live in `watch.py`, which is a pure reader and stays that way; everything
that acts is here.

The owner's rule, in his words and in this order:

    after three minutes it nudges the director with one phrase,
    "write Claude the next action", every three minutes, three times total;
    then the director writes to the executor. If the executor is working
    anyway, the count goes back to zero.

Four things follow, none negotiable:

1. **Both sides are read before anything is sent.** A director sitting quiet
   while the executor builds is the normal shape of the work, not a fault.
   Nudging through it is the behaviour that wore the owner out.
2. **One phrase, never reworded.** Asked whose turn it is, the director
   answers with a plan and sends nothing. Told plainly to write to Claude, it
   writes.
3. **Success is a message landing in the executor's window**, not a reply from
   the director. "I will now gather myself" delivers nothing.
4. **Three strikes, then it changes who it talks to.** After three unanswered
   calls it turns to the executor once — not to nudge it into working, but to
   ask it to find out why the other side went quiet. Only then does it stop
   and ask for the owner. A frozen board in the morning beats a thousand
   nudges overnight.

### Who is who

Nobody should have to type session ids. The pair is resolved two ways, and a
pin always beats a guess:

    pinned    state/pair.json, written by hand or by an accepted detection
    detected  the live executor window, and the director's most recent thread
              in this working directory

Detection refuses rather than guesses: two live executor windows, or no
director thread in this directory, is an answer of "I don't know", never a
coin flip. The pair is re-checked on every tick — a dead window or a vanished
thread stops the nudge instead of sending it somewhere wrong.

### It does not start itself

There is no service, no timer and no installer in this project. One
invocation is one tick, and without `--arm` a tick only says what it would
have done.
"""

import argparse
import datetime as dt
import glob
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import watch  # noqa: E402

# The one phrase. Every other wording sends the director off to plan instead
# of to write, which is the whole failure this tool exists to end.
PHRASE = "Напиши Клоду следующее действие"

# After three unanswered strikes the watchman stops talking to the director
# and turns to the executor instead. Not to nudge it into working — if it were
# working none of this would be happening — but to ask it to find out why the
# other side went quiet. A silent director is a fact somebody has to explain,
# and the executor is the one that can look.
ASK_PHRASE = ("Директор молчит и не ответил на три вызова подряд. "
              "Выясни, почему он уснул, и доложи владельцу.")

QUIET_BEFORE_STRIKE = 180          # three minutes
BETWEEN_STRIKES = 180              # three minutes
MAX_STRIKES = 3

CODEX = "/Applications/ChatGPT.app/Contents/Resources/codex"
CODEX_TIMEOUT = 120
ROOT = os.environ.get("AION_ROOT", ".")
PASSPORTS = os.path.expanduser("~/.claude/sessions")

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "..", "state", "watchman.json")
PAIR = os.path.join(HERE, "..", "state", "pair.json")
LEDGER = os.path.join(HERE, "..", "state", "watchman-ledger.ndjson")

NONE = "NONE"
STRIKE = "STRIKE"
ASK_EXECUTOR = "ASK_EXECUTOR"
STOP = "STOP"
BLIND = "BLIND"


# ---------------------------------------------------------------- state

def load(path, fallback):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return dict(fallback)


def save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def load_state():
    return load(STATE, {"strikes": 0, "last_strike_epoch": None,
                        "stopped": False, "asked_executor": False})


def note(**fields):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    entry = {"at": round(time.time(), 1), **fields}
    with open(LEDGER, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


# ---------------------------------------------------------------- app-server

def app_server(steps, timeout=CODEX_TIMEOUT):
    """Run a short conversation with the local app-server and hand back replies.

    `steps` is a list of (method, params). The reply to each is returned in
    order. Nothing here reaches the network: it is a local process over stdio.
    """
    proc = subprocess.Popen([CODEX, "app-server", "--listen", "stdio://"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, bufsize=1)
    started, counter, replies, deltas = time.time(), [0], [], []

    def call(method, params):
        counter[0] += 1
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": counter[0],
                                     "method": method, "params": params},
                                    ensure_ascii=False) + "\n")
        proc.stdin.flush()
        return counter[0]

    def until(predicate):
        while time.time() - started < timeout:
            line = proc.stdout.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if message.get("method") == "item/agentMessage/delta":
                deltas.append((message.get("params") or {}).get("delta", ""))
            if predicate(message):
                return message
        return None

    try:
        rid = call("initialize", {"clientInfo": {"name": "aion-watchman",
                                                 "title": "Watchman", "version": "1"}})
        until(lambda m: m.get("id") == rid)
        for method, params in steps:
            if method == "turn/start":
                rid = call(method, params)
                replies.append(until(
                    lambda m: str(m.get("method", "")).startswith("turn/completed")))
            else:
                rid = call(method, params)
                replies.append(until(lambda m: m.get("id") == rid))
    finally:
        try:
            proc.stdin.close()
            proc.terminate()
            proc.wait(timeout=8)
        except Exception:
            proc.kill()
    return replies, "".join(deltas).strip()


# ---------------------------------------------------------------- who is who

def live_windows(root=PASSPORTS):
    """Executor windows whose process is actually alive.

    A passport left behind by a closed editor is not a window. The pid decides.
    """
    found = []
    for path in sorted(glob.glob(os.path.join(root, "*.json"))):
        try:
            with open(path, encoding="utf-8") as handle:
                passport = json.load(handle)
        except (OSError, ValueError):
            continue
        session, pid = passport.get("sessionId"), passport.get("pid")
        if not session or not pid:
            continue
        try:
            os.kill(int(pid), 0)
        except (OSError, ValueError, TypeError):
            continue
        found.append({"session": session, "pid": pid,
                      "cwd": passport.get("cwd"), "passport": path})
    return found


def director_threads(root=ROOT, limit=20):
    """Director threads in this working directory, most recently touched first."""
    replies, _ = app_server([("thread/list", {"limit": limit})], timeout=40)
    reply = replies[0] if replies else None
    rows = (((reply or {}).get("result") or {}).get("data")) or []
    here = [t for t in rows if t.get("cwd") == root]
    here.sort(key=lambda t: t.get("updatedAt") or 0, reverse=True)
    return [{"thread": t.get("id"), "updated": t.get("updatedAt"),
             "status": (t.get("status") or {}).get("type"),
             "preview": (t.get("preview") or "")[:60]} for t in here]


def detect(root=ROOT, passports=PASSPORTS, windows=None, threads=None):
    """Propose a pair. Refuses to guess when the answer is not obvious."""
    windows = live_windows(passports) if windows is None else windows
    threads = director_threads(root) if threads is None else threads
    out = {"claude_session": None, "codex_thread": None, "how": "detected",
           "confident": True, "why": [], "windows": windows, "threads": threads[:3]}

    if len(windows) == 1:
        out["claude_session"] = windows[0]["session"]
    elif not windows:
        out["confident"] = False
        out["why"].append("no live executor window")
    else:
        out["confident"] = False
        out["why"].append("%d live executor windows — say which" % len(windows))

    if threads:
        out["codex_thread"] = threads[0]["thread"]
        if len(threads) > 1:
            gap = (threads[0]["updated"] or 0) - (threads[1]["updated"] or 0)
            if gap < 600:
                out["confident"] = False
                out["why"].append("two director threads touched %ds apart" % gap)
    else:
        out["confident"] = False
        out["why"].append("no director thread in %s" % root)

    return out


def resolve(thread=None, session=None):
    """Arguments beat the pin; the pin beats detection; detection may refuse."""
    pinned = load(PAIR, {})
    pair = {"codex_thread": thread or pinned.get("codex_thread"),
            "claude_session": session or pinned.get("claude_session"),
            "how": "argument" if (thread or session) else
                   ("pinned" if pinned.get("codex_thread") else "detected")}
    if pair["codex_thread"] and pair["claude_session"]:
        pair["confident"] = True
        return pair
    found = detect()
    pair["codex_thread"] = pair["codex_thread"] or found["codex_thread"]
    pair["claude_session"] = pair["claude_session"] or found["claude_session"]
    pair["confident"] = found["confident"]
    pair["why"] = found["why"]
    return pair


def still_there(pair):
    """Re-check the pair before acting. Wrong target is worse than no action."""
    problems = []
    if not pair.get("claude_session"):
        problems.append("no executor session")
    elif pair["claude_session"] not in [w["session"] for w in live_windows()]:
        problems.append("executor window %s is not alive" % pair["claude_session"][:8])
    if not pair.get("codex_thread"):
        problems.append("no director thread")
    else:
        try:
            watch.codex_journal(pair["codex_thread"])
        except (FileNotFoundError, ValueError):
            problems.append("director thread %s has no journal" % pair["codex_thread"][:8])
    return problems


# ---------------------------------------------------------------- the hand

def strike(thread_id, phrase=PHRASE):
    """Resume the director's own thread and put the phrase into it.

    Its own thread, not a fresh one: a new thread knows nothing of the work
    and "the next action" would mean nothing to it.
    """
    replies, said = app_server([
        ("thread/resume", {"threadId": thread_id}),
        ("turn/start", {"threadId": thread_id,
                        "input": [{"type": "text", "text": phrase}]}),
    ])
    resumed = (((replies[0] or {}).get("result") or {}).get("thread") or {})
    if resumed.get("id") != thread_id:
        return {"delivered": False, "why": "thread %s did not resume" % thread_id[:8]}
    done = replies[1] if len(replies) > 1 else None
    return {"delivered": bool(done), "why": "" if done else "turn did not complete",
            "director_said": said[:500]}


def ask_executor(phrase=ASK_PHRASE):
    """Put the question into the executor's own window, through the link.

    The same door the director uses, so there is one way in and not two.
    """
    link = os.path.join(HERE, "link.py")
    done = subprocess.run([sys.executable, link, "send", phrase],
                          capture_output=True, text=True, timeout=60)
    ok = done.returncode == 0
    return {"delivered": ok,
            "why": "" if ok else ((done.stderr or done.stdout or "").strip()[:200])}


def landed_in_window(session_id, since_epoch):
    """Did a new message actually arrive in the executor's window?

    The only measure of success. The director claiming it will write does not
    count, and never has.
    """
    if since_epoch is None:
        return False
    records = watch.parse_lines(watch.read_tail(watch.claude_journal(session_id))[0])
    return any(t["started_epoch"] and t["started_epoch"] > since_epoch
               for t in watch.claude_turns(records))


# ---------------------------------------------------------------- the rule

def decide(codex, claude, state, now, delivered=False):
    """One tick of the owner's rule. Returns (action, reason, next_state)."""
    strikes = state.get("strikes", 0)
    last = state.get("last_strike_epoch")
    nxt = dict(state)

    # First on purpose. A long build, a long search, a long report — all of it
    # is normal, and the director being quiet through it is also normal.
    if claude["state"] == watch.WORKING:
        nxt.update(strikes=0, last_strike_epoch=None, stopped=False, asked_executor=False)
        return NONE, "executor is working — count reset to zero", nxt

    if delivered:
        nxt.update(strikes=0, last_strike_epoch=None, stopped=False, asked_executor=False)
        return NONE, "a message landed in the executor's window — count reset", nxt

    if codex["state"] == watch.WORKING:
        return NONE, "director is mid-turn — nothing to nudge", nxt

    if state.get("stopped"):
        return STOP, "already stopped after %d strikes — waiting for the owner" % strikes, nxt

    quiet = codex["silence_seconds"]
    if quiet is None:
        return NONE, "director's silence cannot be measured", nxt
    if quiet < QUIET_BEFORE_STRIKE:
        return NONE, "director quiet only %ds of %ds" % (quiet, QUIET_BEFORE_STRIKE), nxt

    if strikes >= MAX_STRIKES:
        # Three strikes spent on a director that will not answer. Turn to the
        # executor once and ask it to find out why, then stop for good.
        if not state.get("asked_executor"):
            nxt.update(asked_executor=True, last_strike_epoch=now)
            return ASK_EXECUTOR, ("%d strikes unanswered — asking the executor "
                                  "why the director went quiet" % strikes), nxt
        nxt["stopped"] = True
        return STOP, ("%d strikes and the executor was asked too — "
                      "the owner is needed" % strikes), nxt

    if last is not None and (now - last) < BETWEEN_STRIKES:
        return NONE, "%ds since the last strike, waiting out %ds" % (
            now - last, BETWEEN_STRIKES), nxt

    nxt.update(strikes=strikes + 1, last_strike_epoch=now)
    return STRIKE, "both quiet, director silent %ds — strike %d of %d" % (
        quiet, strikes + 1, MAX_STRIKES), nxt


# ---------------------------------------------------------------- one tick

def tick(now, armed=False, thread=None, session=None, state=None):
    state = load_state() if state is None else state
    pair = resolve(thread, session)
    problems = still_there(pair)

    if problems:
        result = {"action": BLIND, "reason": "; ".join(problems), "armed": armed,
                  "pair": pair, "at_utc": watch.utc_iso(now),
                  "at_local": watch.local_iso(now)}
        note(action=BLIND, reason=result["reason"], armed=armed)
        return result

    codex = watch.observe_codex(pair["codex_thread"], now=now)
    claude = watch.observe_claude(pair["claude_session"], now=now)
    delivered = landed_in_window(pair["claude_session"], state.get("last_strike_epoch"))

    action, reason, nxt = decide(codex, claude, state, now, delivered)

    acting = (STRIKE, ASK_EXECUTOR)
    delivery = None
    if action in acting and not pair.get("confident", True):
        action, reason = BLIND, "not sure who is who: " + "; ".join(pair.get("why", []))
        nxt = dict(state)
    elif action == STRIKE and armed:
        delivery = strike(pair["codex_thread"])
    elif action == ASK_EXECUTOR and armed:
        delivery = ask_executor()
    elif action in acting:
        delivery = {"delivered": False, "why": "not armed — nothing was sent"}
        nxt = dict(state)                    # a dry run must spend nothing

    result = {
        "action": action,
        "reason": reason,
        "armed": armed,
        "phrase": {STRIKE: PHRASE, ASK_EXECUTOR: ASK_PHRASE}.get(action),
        "pair": pair,
        "codex": {"state": codex["state"], "silence_seconds": codex["silence_seconds"]},
        "claude": {"state": claude["state"], "silence_seconds": claude["silence_seconds"]},
        "loop": watch.loop_verdict(codex, claude),
        "strikes_before": state.get("strikes", 0),
        "strikes_after": nxt.get("strikes", 0),
        "landed_since_last_strike": delivered,
        "at_utc": watch.utc_iso(now),
        "at_local": watch.local_iso(now),
    }
    if delivery is not None:
        result["delivery"] = delivery

    save(STATE, nxt)
    note(action=action, reason=reason, armed=armed, strikes_after=nxt.get("strikes", 0))
    return result


# ---------------------------------------------------------------- cli

def main(argv=None):
    parser = argparse.ArgumentParser(description="watch both agents; nudge one. off unless armed")
    parser.add_argument("command", choices=["tick", "pair", "detect", "status", "reset"])
    parser.add_argument("--thread", help="director thread id; overrides the pin")
    parser.add_argument("--session", help="executor session id; overrides the pin")
    parser.add_argument("--arm", action="store_true",
                        help="actually send; without it a tick only reports")
    parser.add_argument("--now", type=float, default=None)
    args = parser.parse_args(argv)

    def out(data):
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0

    if args.command == "detect":
        return out(detect())
    if args.command == "pair":
        if args.thread or args.session:
            found = detect() if not (args.thread and args.session) else {}
            save(PAIR, {"codex_thread": args.thread or found.get("codex_thread"),
                        "claude_session": args.session or found.get("claude_session"),
                        "how": "set", "pinned_at": watch.utc_iso(time.time())})
        return out({"pinned": load(PAIR, {}), "resolved": resolve()})
    if args.command == "status":
        return out({"state": load_state(), "pair": load(PAIR, {}), "phrase": PHRASE,
                    "quiet_before_strike_s": QUIET_BEFORE_STRIKE,
                    "between_strikes_s": BETWEEN_STRIKES, "max_strikes": MAX_STRIKES})
    if args.command == "reset":
        save(STATE, {"strikes": 0, "last_strike_epoch": None, "stopped": False})
        return out(load_state())

    now = args.now if args.now is not None else dt.datetime.now(dt.timezone.utc).timestamp()
    return out(tick(now, armed=args.arm, thread=args.thread, session=args.session))


if __name__ == "__main__":
    sys.exit(main())
