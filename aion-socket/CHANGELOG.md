# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2026-09-20

### The first full round
Director decided, gate dispatched, socket delivered, executor built and
reported, three-vote judge passed, gate wrote DONE and named the next item.
Nothing between the steps was done by hand. `N-L0-04` is the first item to
go through the whole loop.

### Added
- `sudya/` — a three-reading judge on top of `inspect_ai`, with a provider
  that drives the local Codex over stdio. Each reading is a fresh thread, so
  three votes are three votes. Passes on at least two of three.
- `director.py judge` now calls that judge. The single-voice call is gone.
- Watchman: after three unanswered strikes it turns to the executor once, by
  the owner's rule, before stopping.

### Known
- `sudya/` is written in Russian; the rest of the project is English. To be
  translated before this becomes more than a backup.
- The director opens its thread `ephemeral`, which leaves the watchman
  nothing to knock on. Fix before the watchman is armed.

## [0.3.0] - 2026-09-19

### Added
- `src/watchman.py` — the one command: finds both agents, watches both, nudges
  the director. One phrase, three minutes apart, three strikes, then it stops
  and asks for the owner. **Off unless armed**: no service, no timer, no
  installer.
- Pair resolution, so no one types session ids. Argument beats pin, pin beats
  detection. The executor side comes from the window passports, where the pid
  decides; the director side from the app-server's thread list narrowed to the
  working directory.
- `tests/test_watchman.py` — 31 probes, none of which send anything anywhere.

### Changed
- Eyes and hand were briefly two commands. Merged: from outside it is one job,
  and two names for it only cost the reader. `watch.py` remains as the reader
  underneath and stays a pure reader.

### Decided
- **Detection refuses rather than guesses.** Two live executor windows, no
  thread in this directory, or two threads touched within ten minutes are all
  an answer of "I don't know". An unsure pair never strikes, even when armed.
- **The pair is re-checked every tick.** A closed window or a vanished thread
  stops the hand rather than aiming it somewhere wrong.
- **A working executor zeroes the count, whatever the director is doing.**
  A job may run half an hour; nudging through it is the behaviour this tool
  exists to prevent, so that clause is evaluated first.
- **Success is a message landing in the executor's window**, never a reply
  from the director. Measuring the reply is how a nudge becomes an echo.
- **The phrase is a constant, and a probe asserts it holds no question mark.**
  Asked whose turn it is, the director plans and sends nothing; told plainly
  to write, it writes.
- **Strikes go into the director's own thread** via `thread/resume`. A fresh
  thread knows nothing of the work.
- A dry run spends no strike, so the rule can be watched for as long as the
  owner wants before anything is armed.

### Known
- Resuming a thread appends to that thread's journal, so a strike is visible
  in the evidence the observer reads. The observer itself never resumes.

## [0.2.0] - 2026-09-19

### Added
- `src/watch.py` — a read-only activity observer over the journals both
  agents already write. Reports one of `WORKING`, `IDLE`, `TOOL_ACTIVITY`,
  `TEXT_ONLY`, `COMPLETED` (plus `UNKNOWN`) per side, and a loop verdict
  across both. Takes no action and wakes no one, by design.
- `tests/test_watch.py` — 31 probes: built fixtures pin each state to a fixed
  clock, live replays run the same parser over the real journals.

### Decided
- **Where an agent declares the end of its own turn, that declaration wins.**
  The first version treated a growing journal as work in progress even after
  `task_complete`. A probe caught it. Records that land after the end marker
  are bookkeeping, not work.
- **A turn that opened and never closed reports `UNKNOWN`, not `WORKING`.**
  An agent that died mid-turn must not keep a busy light on forever.
- **Codex is bound to a named thread id.** Observing "the newest journal"
  silently watches the wrong conversation, which is worse than failing.
- **Both sides are read at once.** One quiet while the other works is normal;
  only both quiet is a stall.

### Measured
- 112 real codex turns on this disk: 46 called a tool, **64 produced text and
  called nothing**, 2 neither. Better than half of all turns were talk.
- A live reading with the director idle 90 minutes and the executor mid-task
  returned `EXECUTOR_WORKING`, `stalled: false` — the case that must never
  trigger a nudge.
- Observing a 60 MB journal three times left it byte-identical, mtime
  unchanged.

## [0.1.0] - 2026-09-19

First working version.

### Added
- `src/link.py` — local delivery into a live executor window over an
  `AF_UNIX` socket, and reading the reply from a pre-send transcript mark.
- `src/director.py` — decide, dispatch and judge, driving the checklist gate
  without bypassing any of its rules.
- MIT license, README with the weak spots stated plainly.

### Verified
- The director read the board on its own, took the next item, read its
  acceptance criteria and wrote a brief for the executor. No network.
- `link.py windows` lists live windows and the chosen one.
- The three local helpers this builds on make zero network calls — checked
  by inspection.

### Not yet verified
- A full round with a recorded verdict has not been run end to end.

### Replaced
An earlier transport carried the same messages through a repository and a
browser window. Over one day it lost 32 deliveries to a missing input field
and 18 to a busy transport lock. None of those failure modes exist here:
there is nothing between the two agents to fail.
