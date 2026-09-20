# AION Socket

A direct link between two coding agents running on the same machine.
No network, no message broker, no browser, no repository in the middle.

One agent directs, the other executes. They share a computer, a user account
and a disk, so they do not need the internet to talk — only a door.

## How it works

```
director  ──▶  window passport   ~/.claude/sessions/<pid>.json
          ──▶  AF_UNIX socket    (address taken from that passport)
          ──▶  executor window   the text appears as an ordinary message

executor  ──▶  replies in its own window
director  ──▶  reads that window's transcript from a mark taken before sending
```

`AF_UNIX` is not a network socket. It has no internet address, no port and no
route off this machine. Unplug the network and the link keeps working.

The mark matters: the reply is read **from the exact offset recorded before
the message was sent**, so earlier text is never mistaken for an answer.

## Install

Requires Python 3.9+ and nothing else. No third-party packages.

```bash
git clone <this repo>
cd aion-socket
python3 src/link.py windows
```

## Usage

Link, either direction:

```bash
python3 src/link.py windows                list live executor windows
python3 src/link.py send "text"            deliver a message
python3 src/link.py read <mark> [session]  read what was said after a mark
python3 src/link.py round "text"           deliver, wait, print the reply
```

Director, one item at a time:

```bash
python3 src/director.py decide   write the brief, send nothing
python3 src/director.py round    dispatch the next item to the executor
python3 src/director.py judge    judge the evidence, record the verdict
```

## Watchman — one command that watches both and nudges one

`src/watchman.py` is the only command here anyone needs to type. It finds both
agents by itself, reads what each is doing, and nudges the director when — and
only when — the work has genuinely stopped.

```bash
python3 src/watchman.py tick          look at both, report; may nudge with --arm
python3 src/watchman.py detect        who it thinks the two sides are
python3 src/watchman.py pair          show or pin the pair
python3 src/watchman.py status        strike count, thresholds, phrase
python3 src/watchman.py reset         clear the count
```

No session ids on the command line. It works them out, and refuses to guess.

### The eyes

`src/watch.py` is the reader underneath, and stays a pure reader: it never
sends, never writes to a journal, and wakes no one. It answers one question
about each side, without believing a word either agent says about itself:

> is it working right now, and if not, what did its last turn actually do?

Both agents already keep a journal on this disk. Nothing has to be
instrumented, wrapped or asked. Its output carries the state, the reason for
it, the seconds of silence, what the last turn did, and a sha256 of the exact
bytes read.

### The five states

| state | what it means |
|---|---|
| `WORKING` | a turn is in flight, or the journal is still growing |
| `IDLE` | silent longer than the threshold |
| `TOOL_ACTIVITY` | last finished turn called tools |
| `TEXT_ONLY` | last finished turn produced text and called nothing |
| `COMPLETED` | turn finished, kind indeterminate |

`IDLE` outranks the last two on purpose: what a turn did an hour ago does not
describe what is happening now. A sixth value, `UNKNOWN`, covers a turn that
opened and never closed — an agent that died mid-turn must not keep shining a
busy light.

### Why it reads both sides at once

One side quiet while the other works is normal and must never be treated as a
fault. Only both quiet at the same time is a stall. `loop_verdict` reports
`BOTH_WORKING`, `EXECUTOR_WORKING`, `DIRECTOR_WORKING` or `BOTH_QUIET`, and
sets `stalled` only in the last case past the threshold.

### What the two journals actually offer

They are not symmetrical, and the observer does not pretend they are.

- **Codex** writes `task_started` and `task_complete`, and records every tool
  call. Where that end marker exists it is the authority: a journal line
  landing after it is bookkeeping, not work.
- **The Claude session journal** has no end-of-turn marker. On that side
  growth is the only honest evidence of work in progress.

### Measured on the real journals, 2026-09-19

112 turns across the codex journals on this disk:

```
 46  TOOL_ACTIVITY   called at least one tool
 64  TEXT_ONLY       produced text, called nothing
  2  COMPLETED       neither
```

Better than half of all turns produced talk and no action. That number is the
reason this observer exists.

### Who is who

Nobody should have to type session ids, and nothing should be guessed. The
pair is resolved three ways, and the more explicit always wins:

| source | how it is found |
|---|---|
| argument | `--thread` / `--session` on the command line |
| pinned | `state/pair.json`, written by `pair` |
| detected | the live executor window, and the director's newest thread here |

The executor side comes from the window passports in `~/.claude/sessions`,
and the pid decides: a passport left behind by a closed editor is not a
window. The director side comes from the app-server's own thread list,
narrowed to this working directory.

Detection **refuses rather than guesses**. Two live executor windows, no
thread in this directory, or two threads touched within ten minutes of each
other all produce an answer of "I don't know", and an unsure pair never
strikes — not even when armed. The pair is re-checked every tick, so a closed
window or a vanished thread stops the hand instead of aiming it somewhere
wrong.

### The rule

| seen | done |
|---|---|
| executor working | nothing — **count back to zero** |
| director mid-turn | nothing |
| director quiet under 3 min | nothing |
| both quiet past 3 min | one strike, then wait 3 min |
| 3 strikes, nothing delivered | stop, ask the owner |
| a message landed in the executor's window | count back to zero |

The first row carries the design. A director sitting quiet while the executor
builds is the normal shape of the work, not a fault. A job may take half an
hour; nudging through it is the behaviour this tool exists to prevent.

### One phrase, never reworded

```
Напиши Клоду следующее действие
```

Asked whose turn it is, the director answers with a plan and sends nothing.
Told plainly to write to the executor, it writes. The phrase is a constant in
the source and a probe asserts it contains no question mark.

### What counts as success

A new message appearing in the executor's window. Not a reply from the
director — "I will now gather myself" is a reply, and it delivers nothing.
Measuring the reply instead of the delivery is how a nudge turns into an
endless echo.

### Where it strikes

Into the director's own thread, via `thread/resume` on the local app-server.
A fresh thread knows nothing of the work, so "the next action" would mean
nothing to it.

Note that resuming a thread appends to that thread's journal. The observer
never does this; only a strike does.

## Rules it does not bend

AION Socket decides nothing on its own. Every rule lives in the checklist
gate it calls:

- exactly one item in progress;
- the executor may return `PASS_CANDIDATE`, `FAIL` or `BLOCKED` — never `DONE`;
- only the gate writes `DONE`, and only on the director's verdict with the
  required evidence present;
- the director does not build; the executor does not approve itself.

## Layout

```
src/link.py       the door: deliver into a window, read the reply back
src/director.py   decide, dispatch, judge; drives the gate, never bypasses it
src/watch.py      the eyes: a pure reader over both agents' journals
src/watchman.py   the one command: find both, watch both, nudge one
tests/            probes
state/            the pinned pair, the strike count, the ledger
evidence/         dated observer readings, kept for the record
LICENSE           MIT
```

## Known weak spots

Stated plainly, because a tool that hides these is worse than one that has
none.

1. **A live executor window is required.** Close the editor and delivery
   fails. That is the price of the executor being a session rather than a
   daemon.
2. **The judge is inconsistent.** Asked twice about identical evidence, the
   reviewing model returned `PASS` once and `FAIL` once. Good work will
   occasionally be sent back.
3. **Reply detection is a heuristic.** The link treats the answer as finished
   when it stops growing. A long answer may be cut short; a silent executor
   hangs until the timeout.
4. **No retry.** If delivery fails, nothing tries again.
5. **The observer reads a tail, not a whole journal.** Default 2 MB. A turn
   older than that window is invisible to it, and on a very long turn the
   opening `task_started` can fall out of view.
6. **A paused agent and a dead agent look alike.** Silence is silence. The
   observer reports how long, never why.

## Design notes

Wrapping both agents — intercepting their startup so every message passes
through this project — would fix items 1, 3 and 4. It was rejected on
purpose: it places thousands of lines of intermediary on the narrowest part
of the system, and a failure there takes both agents down at once. A door
that occasionally needs a second knock is safer than a corridor that can
collapse.

The same reasoning applies to protocol layers. Both agents support tool
protocols that could carry these messages. That would make the call more
convenient, not more reliable, so it stays out until a measured failure
demands it.

## License

MIT. See `LICENSE`.
