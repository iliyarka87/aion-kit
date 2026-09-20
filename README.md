# AION kit

Mechanical guardrails that let a coding agent (Claude Code, Codex, …) work through a long checklist
**unattended** — overnight, without a human clicking "allow", without skipped items and without
"done" that nobody verified.

Five parts, each usable on its own:

| part | what it is | start here |
|---|---|---|
| [`aion-checklist/`](aion-checklist/) | the **gate**: a mechanical lock on a checklist — one item in work, dependencies enforced, `DONE` only by the controller and only with evidence, every refusal journaled | `python3 sobrat.py` → `python3 proby.py` |
| [`aion-loop/`](aion-loop/) | the **loop**: director → executor → judge → gate, driven by a small "hand" process; registries of failures, decisions, invariants; a change gate with eight refusal conditions; a PreToolUse hook for Claude Code; stable/candidate/rollback | [`aion-loop/README.md`](aion-loop/README.md), `python3 proverit-komplekt.py` |
| [`aion-socket/`](aion-socket/) | the **door**: a direct AF_UNIX link into a live Claude Code window on the same machine — the hand drops a task into the window as an ordinary message and reads the reply from an exact offset | [`aion-socket/README.md`](aion-socket/README.md), `python3 -m unittest discover -s tests` |
| [`svyaz/`](svyaz/) | the **link**: director → executor contract — task packet with mandatory fields, a shared vocabulary of terminal markers, idempotent delivery keyed by `item:attempt`, recovery after restart | [`svyaz/README.md`](svyaz/README.md) |
| [`aion-router/`](aion-router/) | the **router** (optional): one stable plan per task, model/effort chosen by task family with spend protection, separate lanes per chat | [`aion-router/README.md`](aion-router/README.md) |

## What problem this solves

An agent left alone with a 69-item plan will (we measured this on ourselves): forget where it stopped after a
context reset, report "done" without a check, jump ahead of unmet dependencies, quietly widen the task, and
stall on a permission popup until morning. The kit turns each of those into a machine refusal:

- **one item at a time, dependencies locked** — the gate refuses `dispatch` of an item whose dependencies are not `DONE`;
- **DONE requires evidence** — the worker can only return `PASS_CANDIDATE | FAIL | BLOCKED`; the controller writes `DONE`
  after an independent judge and only with evidence files (`validate --by director --evidence …`);
- **judge ≠ builder** — verdicts carry the identities of both; a fresh process judges, never the window that built;
- **failures become guards** — every failure is a 17-field record; its signature blocks the same action next time,
  a third repeat of a family forbids patches until a written hypothesis;
- **no popups** — a missing permission becomes a file (capability request / owner decision queue); the dependent
  branch blocks, everything else continues;
- **state on disk, not in the agent's head** — the board, the queue, deliveries and journals survive session death;
  the hand restarts, reconciles and resumes from the same point.

## Install

See [INSTALL.md](INSTALL.md) — Linux/macOS, Windows (WSL2 recommended), and "solo" mode without Codex.
Requirements: Python 3.9+, `git`. No third-party packages (the optional judge environment needs Python 3.12 + `inspect_ai`).

Quick check that the kit is intact on your machine:

```bash
cd aion-checklist && python3 sobrat.py && python3 proby.py        # gate probes → "ВСЕ ПРОБЫ СОШЛИСЬ" (all probes passed)
cd ../aion-loop   && python3 proverit-komplekt.py                  # manifest fingerprints
python3 bin/markery.py --proby && python3 bin/dogovor_zadachi.py --proby
cd ../aion-socket && python3 -m unittest discover -s tests -q
```

## Honest limits

- **Language.** Documentation, examples and registry samples are in English. The *code* — identifiers, console
  messages, docstrings — is in Russian (it was built that way, live, on a real project). It runs the same; reading
  it needs Russian or a translator. Translating the code is on the roadmap (v0.2).
- **Snapshot.** This is the kit as it ran on 2026-09-20 after 27 of 69 checklist items; the canon it came from has
  moved on (state machines, checkpoints, capability requests, promotion/observation). They arrive in v0.2.
- **Platform.** Built and tested on macOS with Python 3.9; the socket, the process lock and `nohup` are Unix. On
  Windows use WSL2 (see INSTALL.md). `sync/` contains macOS `launchd` files — examples, not requirements.
- **External pieces are optional.** Codex as director/judge, the `inspect_ai` judge environment and Claude Code as
  the executor are what *we* use; INSTALL.md shows the solo path with `claude -p`.
- **What is not here.** Our company's checklist (the 69 items), our Master document and our registries are not
  part of the kit — you bring your own checklist (`aion-checklist/examples/example-checklist.md` shows the format).
  No keys, no personal paths: the kit was scanned before publishing.

## Layout of a project that uses the kit

```
your-project/
├── AION/                      your product
├── 01-MASTER.md               your laws and your checklist (any name; sobrat.py reads AION_CHECKLIST_SOURCE)
└── aion-kit/                  this repository (or just the parts you use)
```

## License

MIT — see [LICENSE](LICENSE). Use it, change it, ship it; keep the copyright line.
Questions and bugs: GitHub Issues. Checklists and practices worth discussing: GitHub Discussions.
