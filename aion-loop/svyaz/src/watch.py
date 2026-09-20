#!/usr/bin/env python3
"""AION Watch — a read-only activity observer for two agent journals.

It answers one question about each side of the link, without believing a word
either agent says about itself:

    is it working right now, and if not, what did its last turn actually do?

Both agents already keep a journal on this disk. Codex writes an explicit
`task_started` / `task_complete` pair and records every tool call. The Claude
session journal records each message and every `tool_use` block. Neither has
to be asked, instrumented or trusted — the evidence is already there.

Nothing here writes to a journal, sends a message, or wakes anyone. It reads
and reports. Acting on the report is a separate tool that does not exist yet,
on purpose.

States, in strict precedence order:

    WORKING         a turn is in flight, or the journal grew just now
    IDLE            silent for longer than the idle threshold
    TOOL_ACTIVITY   last finished turn called tools
    TEXT_ONLY       last finished turn produced text and called nothing
    COMPLETED       last turn finished, kind indeterminate

IDLE outranks TOOL_ACTIVITY and TEXT_ONLY on purpose: what a turn did an hour
ago does not describe what is happening now.

Time: every timestamp is normalised to epoch seconds UTC on the way in.
Journal timestamps are ISO-8601 with a `Z` suffix; file mtimes are epoch
already. Local time appears only in the human-readable output, always with
its offset spelled out, and is never compared against anything.
"""

import argparse
import datetime as dt
import glob
import hashlib
import json
import os
import sys

WORKING = "WORKING"
IDLE = "IDLE"
TOOL_ACTIVITY = "TOOL_ACTIVITY"
TEXT_ONLY = "TEXT_ONLY"
COMPLETED = "COMPLETED"
UNKNOWN = "UNKNOWN"

STATES = (WORKING, IDLE, TOOL_ACTIVITY, TEXT_ONLY, COMPLETED, UNKNOWN)

# A turn still growing counts as working for this long after its last record.
# Generous on purpose: the executor may think, read and search for minutes
# between two journal lines, and calling that "idle" is the error that hurts.
WORKING_WINDOW = 90

# Silence longer than this is idleness rather than a pause inside a turn.
IDLE_AFTER = 180

# The Claude journal runs to tens of megabytes. Only the tail is ever read.
TAIL_BYTES = 2_000_000

CODEX_SESSIONS = os.path.expanduser("~/.codex/sessions")
CLAUDE_PROJECTS = os.path.expanduser("~/.claude/projects")


# ---------------------------------------------------------------- time

def to_epoch(stamp):
    """ISO-8601 (with Z or an offset) -> epoch seconds UTC. None if unusable."""
    if not stamp:
        return None
    text = str(stamp).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:            # naive stamps are declared UTC
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment.timestamp()


def utc_iso(epoch):
    if epoch is None:
        return None
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).isoformat(timespec="seconds")


def local_iso(epoch):
    """Local time with the offset written out, so the two clocks never mix."""
    if epoch is None:
        return None
    return dt.datetime.fromtimestamp(epoch).astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------- reading

def read_tail(path, tail_bytes=TAIL_BYTES):
    """Read the last bytes of a file. Read-only, and never the whole thing.

    Returns (lines, evidence). The first line of a truncated window is dropped
    because it is almost certainly cut in half.
    """
    size = os.path.getsize(path)
    start = max(0, size - tail_bytes)
    with open(path, "rb") as handle:
        handle.seek(start)
        window = handle.read()
    evidence = {
        "path": path,
        "size_bytes": size,
        "mtime_epoch_utc": os.path.getmtime(path),
        "window_from_byte": start,
        "window_bytes": len(window),
        "window_sha256": hashlib.sha256(window).hexdigest(),
        "truncated": start > 0,
    }
    text = window.decode("utf-8", "replace")
    lines = text.split("\n")
    if start > 0 and lines:
        lines = lines[1:]
    return [line for line in lines if line.strip()], evidence


def parse_lines(lines):
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue                      # a half-written last line, nothing more
    return out


# ---------------------------------------------------------------- codex

def codex_journal(thread_id, root=CODEX_SESSIONS):
    """Find the journal of ONE named thread.

    Deliberately not "the newest file": the newest thread is often some other
    conversation, and observing the wrong one silently is worse than failing.
    """
    if not thread_id:
        raise ValueError("a codex thread id is required; 'latest' is not accepted")
    hits = sorted(glob.glob(os.path.join(root, "*", "*", "*", "*%s*.jsonl" % thread_id)))
    if not hits:
        raise FileNotFoundError("no codex journal for thread %s under %s" % (thread_id, root))
    return hits[-1]


def codex_turns(records):
    """Fold a codex journal into finished and in-flight turns."""
    turns = {}
    order = []

    def slot(turn_id):
        if turn_id not in turns:
            turns[turn_id] = {
                "turn_id": turn_id, "started_epoch": None, "completed_epoch": None,
                "tool_calls": 0, "assistant_messages": 0, "last_event_epoch": None,
                "last_agent_message": None,
            }
            order.append(turn_id)
        return turns[turn_id]

    current = None
    for record in records:
        stamp = to_epoch(record.get("timestamp"))
        kind = record.get("type")
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        sub = payload.get("type")

        if kind == "event_msg" and sub == "task_started":
            current = payload.get("turn_id")
            turn = slot(current)
            turn["started_epoch"] = to_epoch(record.get("timestamp")) or stamp
            turn["last_event_epoch"] = stamp
        elif kind == "event_msg" and sub == "task_complete":
            turn = slot(payload.get("turn_id") or current)
            turn["completed_epoch"] = stamp
            turn["last_event_epoch"] = stamp
            turn["last_agent_message"] = payload.get("last_agent_message")
            current = None
        elif current is not None:
            turn = slot(current)
            turn["last_event_epoch"] = stamp or turn["last_event_epoch"]
            if kind == "response_item" and sub in ("custom_tool_call", "function_call"):
                turn["tool_calls"] += 1
            elif kind == "response_item" and sub == "message":
                if payload.get("role") == "assistant":
                    turn["assistant_messages"] += 1

    return [turns[t] for t in order], current


def observe_codex(thread_id, now, root=CODEX_SESSIONS, tail_bytes=TAIL_BYTES,
                  working_window=WORKING_WINDOW, idle_after=IDLE_AFTER, path=None):
    path = path or codex_journal(thread_id, root)
    lines, evidence = read_tail(path, tail_bytes)
    records = parse_lines(lines)
    turns, in_flight = codex_turns(records)

    stamps = [to_epoch(r.get("timestamp")) for r in records]
    last_event = max([s for s in stamps if s is not None], default=None)
    last_turn = turns[-1] if turns else None

    return build(
        side="codex", identity=thread_id, evidence=evidence, now=now,
        last_event=last_event, last_turn=last_turn, has_end_marker=True,
        working_window=working_window, idle_after=idle_after,
        records_seen=len(records), turns_seen=len(turns),
    )


# ---------------------------------------------------------------- claude

def claude_journal(session_id, root=CLAUDE_PROJECTS):
    if not session_id:
        raise ValueError("a claude session id is required; 'latest' is not accepted")
    hits = sorted(glob.glob(os.path.join(root, "*", "%s.jsonl" % session_id)))
    if not hits:
        raise FileNotFoundError("no claude journal for session %s under %s" % (session_id, root))
    return hits[-1]


def blocks(record):
    message = record.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if isinstance(content, list):
        return [b.get("type") for b in content if isinstance(b, dict)]
    if isinstance(content, str):
        return ["text"]
    return []


def claude_turns(records):
    """Fold a claude journal into turns.

    A turn opens on a user entry that carries real input rather than a tool
    result, and stays open until the next one. There is no explicit end-of-turn
    record on this side, so "finished" is decided by silence, not by a flag.
    """
    turns = []
    for record in records:
        kind = record.get("type")
        if kind not in ("user", "assistant"):
            continue
        stamp = to_epoch(record.get("timestamp"))
        kinds = blocks(record)

        if kind == "user" and "tool_result" not in kinds:
            turns.append({
                "turn_id": record.get("uuid"), "started_epoch": stamp,
                "completed_epoch": None, "tool_calls": 0,
                "assistant_messages": 0, "last_event_epoch": stamp,
                "last_agent_message": None,
            })
            continue

        if not turns:
            continue
        turn = turns[-1]
        turn["last_event_epoch"] = stamp or turn["last_event_epoch"]
        if kind == "assistant":
            turn["tool_calls"] += kinds.count("tool_use")
            turn["assistant_messages"] += kinds.count("text")
    return turns


def observe_claude(session_id, now, root=CLAUDE_PROJECTS, tail_bytes=TAIL_BYTES,
                   working_window=WORKING_WINDOW, idle_after=IDLE_AFTER, path=None):
    path = path or claude_journal(session_id, root)
    lines, evidence = read_tail(path, tail_bytes)
    records = parse_lines(lines)
    turns = claude_turns(records)

    stamps = [to_epoch(r.get("timestamp")) for r in records]
    last_event = max([s for s in stamps if s is not None], default=None)
    last_turn = turns[-1] if turns else None

    # This side never declares the end of a turn, so growth is the only honest
    # evidence of work in progress.
    return build(
        side="claude", identity=session_id, evidence=evidence, now=now,
        last_event=last_event, last_turn=last_turn, has_end_marker=False,
        working_window=working_window, idle_after=idle_after,
        records_seen=len(records), turns_seen=len(turns),
    )


# ---------------------------------------------------------------- verdict

def build(side, identity, evidence, now, last_event, last_turn, has_end_marker,
          working_window, idle_after, records_seen, turns_seen):
    """Turn the folded journal into one of the five states.

    `has_end_marker` says whether this side declares the end of its own turn.
    Codex does, with `task_complete`. The Claude journal does not, so on that
    side an unfinished turn means nothing and only growth counts.
    """
    silence = None if last_event is None else max(0.0, now - last_event)
    growing = silence is not None and silence <= working_window
    open_turn = (has_end_marker and last_turn is not None
                 and last_turn.get("completed_epoch") is None)

    if last_event is None:
        state = UNKNOWN
        because = "no timestamped record in the window read"
    elif open_turn and silence <= idle_after:
        state = WORKING
        because = "turn opened and not yet closed, quiet %ds" % silence
    elif open_turn:
        # Said it started, never said it finished, and has gone quiet. Calling
        # this WORKING would hide a dead agent behind a busy light forever.
        state = UNKNOWN
        because = "turn opened %ds ago and never closed — may have died mid-turn" % silence
    elif growing and not has_end_marker:
        # Growth only speaks for a side that never says when it is finished.
        # Where `task_complete` exists it is the authority: a journal line
        # landing after it is bookkeeping, not work.
        state = WORKING
        because = "journal grew %ds ago" % silence
    elif silence > idle_after:
        state = IDLE
        because = "silent for %ds, over the %ds threshold" % (silence, idle_after)
    elif last_turn and last_turn["tool_calls"] > 0:
        state = TOOL_ACTIVITY
        because = "last turn made %d tool call(s)" % last_turn["tool_calls"]
    elif last_turn and last_turn["assistant_messages"] > 0:
        state = TEXT_ONLY
        because = "last turn produced text and called no tool"
    else:
        state = COMPLETED
        because = "turn finished, neither tool calls nor text seen in the window"

    turn_out = None
    if last_turn:
        turn_out = {
            "turn_id": last_turn["turn_id"],
            "started_utc": utc_iso(last_turn["started_epoch"]),
            "completed_utc": utc_iso(last_turn["completed_epoch"]),
            "finished": last_turn["completed_epoch"] is not None,
            "tool_calls": last_turn["tool_calls"],
            "assistant_messages": last_turn["assistant_messages"],
            "last_agent_message": last_turn["last_agent_message"],
        }

    return {
        "side": side,
        "identity": identity,
        "state": state,
        "because": because,
        "silence_seconds": None if silence is None else round(silence, 1),
        "last_event_utc": utc_iso(last_event),
        "last_event_local": local_iso(last_event),
        "observed_at_utc": utc_iso(now),
        "observed_at_local": local_iso(now),
        "last_turn": turn_out,
        "counts": {"records_in_window": records_seen, "turns_in_window": turns_seen},
        "thresholds": {"working_window_s": working_window, "idle_after_s": idle_after},
        "evidence": evidence,
    }


def loop_verdict(codex, claude, idle_after=IDLE_AFTER):
    """Read both sides at once. Reports; decides nothing; wakes nobody.

    The rule the owner named: one side quiet while the other works is normal.
    Only both quiet at once is a stall.
    """
    busy = (WORKING,)
    codex_busy = codex["state"] in busy
    claude_busy = claude["state"] in busy

    if codex_busy and claude_busy:
        loop = "BOTH_WORKING"
    elif claude_busy:
        loop = "EXECUTOR_WORKING"
    elif codex_busy:
        loop = "DIRECTOR_WORKING"
    else:
        loop = "BOTH_QUIET"

    silences = [s for s in (codex["silence_seconds"], claude["silence_seconds"]) if s is not None]
    quiet_for = min(silences) if silences else None
    stalled = loop == "BOTH_QUIET" and quiet_for is not None and quiet_for > idle_after

    return {
        "loop_state": loop,
        "stalled": stalled,
        "quiet_for_seconds": quiet_for,
        "note": "observation only — this tool takes no action and wakes no one",
    }


# ---------------------------------------------------------------- cli

def list_threads(root=CODEX_SESSIONS, limit=10):
    hits = glob.glob(os.path.join(root, "*", "*", "*", "rollout-*.jsonl"))
    rows = []
    for path in hits:
        name = os.path.basename(path)[:-6]
        rows.append({
            "thread_id": name.split("-", 7)[-1] if "-" in name else name,
            "mtime_utc": utc_iso(os.path.getmtime(path)),
            "mtime_local": local_iso(os.path.getmtime(path)),
            "path": path,
        })
    rows.sort(key=lambda r: r["mtime_utc"] or "", reverse=True)
    return rows[:limit]


def main(argv=None):
    parser = argparse.ArgumentParser(description="read-only activity observer")
    parser.add_argument("command", choices=["codex", "claude", "both", "threads"])
    parser.add_argument("--thread", help="codex thread id (required; 'latest' not accepted)")
    parser.add_argument("--session", help="claude session id (required; 'latest' not accepted)")
    parser.add_argument("--now", type=float, default=None, help="epoch seconds UTC, for replay")
    parser.add_argument("--idle-after", type=int, default=IDLE_AFTER)
    parser.add_argument("--working-window", type=int, default=WORKING_WINDOW)
    parser.add_argument("--tail-bytes", type=int, default=TAIL_BYTES)
    args = parser.parse_args(argv)

    now = args.now if args.now is not None else dt.datetime.now(dt.timezone.utc).timestamp()
    common = dict(now=now, tail_bytes=args.tail_bytes,
                  working_window=args.working_window, idle_after=args.idle_after)

    if args.command == "threads":
        print(json.dumps(list_threads(), indent=2, ensure_ascii=False))
        return 0
    if args.command == "codex":
        print(json.dumps(observe_codex(args.thread, **common), indent=2, ensure_ascii=False))
        return 0
    if args.command == "claude":
        print(json.dumps(observe_claude(args.session, **common), indent=2, ensure_ascii=False))
        return 0

    codex = observe_codex(args.thread, **common)
    claude = observe_claude(args.session, **common)
    print(json.dumps({
        "codex": codex,
        "claude": claude,
        "loop": loop_verdict(codex, claude, args.idle_after),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
