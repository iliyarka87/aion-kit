# INSTALL

Three things live side by side: **your project**, **your master document with the checklist**, and **this kit**.
This page gets the kit running on your machine — Linux/macOS first, then Windows, then "solo" mode without Codex.

---

## 1. Get the kit

```bash
git clone https://github.com/iliyarka87/aion-kit.git
```
or download the ZIP (Code → Download ZIP) and unpack it next to your project:

```
~/aion/
├── AION/            your product
├── 01-MASTER.md     your laws + your checklist items
└── aion-kit/        this kit
```

## 2. Python

Python **3.9 or newer**, no third-party packages. `git` on PATH.
- Linux / macOS / WSL2: `python3 --version`
- Windows (native): `py -3 --version` or `python --version` — the scripts say `python3`; on native Windows you run them
  as `py -3 script.py` (see §4).

## 3. Bring your own checklist

The gate reads a Markdown source where every item looks like this (full example: `aion-checklist/examples/example-checklist.md`):

```markdown
### N-L0-01 · Machine mirror of state

- CLASS: BUILD_ITEM
- IMPLEMENTATION_MODE: BUILD
- TASK_STATE: PLANNED
- LEVEL: L0
- DEPENDS: N-L0-00
- RISK: GREEN
- REQUIRED_EVIDENCE: state/current.json
- ACCEPTANCE: the mirror equals the document
- INDEPENDENT_REVIEW: NOT REQUIRED (GREEN): automatic check is enough
- OBJECTIVE: state readable by a machine
```

Rules the gate enforces from this: `DEPENDS` are hard locks; `RISK` sets the reference time (GREEN 20 / YELLOW 45 /
RED 90 min — informational, the gate never decides by time); the **last item must be `N-COMPLETE-01`** — the project
completes only through it.

Build the board from your source:

```bash
cd aion-kit/aion-checklist
AION_CHECKLIST_SOURCE=~/aion/01-MASTER.md python3 sobrat.py     # opredelenie.json (immutable definition) + sostoyanie.json (board)
python3 proby.py                                                # gate probes on a fresh board → all passed
python3 vorota.py status                                        # the board
```

Day-to-day (the worker is your agent, the director is you or a second, independent agent):

```bash
python3 vorota.py next-ready                                     # what the gate offers
python3 vorota.py dispatch N-L0-00 --by director                 # one item in work
python3 vorota.py report PASS_CANDIDATE --by worker --evidence evidence/N-L0-00/probes.txt
python3 vorota.py validate N-L0-00 --by director --evidence evidence/N-L0-00/probes.txt   # DONE — only here, only with evidence
python3 vorota.py finding "found X outside the item" --by worker  # recorded; does not change who is in work
```

Every refusal (`dispatch` with unmet dependencies, `validate` without evidence, a second active item, a worker
trying to write DONE) is written to `letopis.ndjson` as `REFUSED` — visible, never silent.

## 4. Windows

**Recommended: WSL2 (Ubuntu inside Windows).** Everything in the kit is Unix-shaped: the AF_UNIX socket into the
Claude window, the single-process lock (`fcntl.flock`), `nohup`, bash timers. In WSL2 all of it works as is;
`launchd` (our macOS supervisor) is replaced by `systemd`/`cron` or simply `nohup`.

1. PowerShell as administrator: `wsl --install -d Ubuntu`, reboot, create a user.
2. In Ubuntu: `sudo apt update && sudo apt install -y python3 python3-venv git`.
3. VS Code: install the "WSL" extension, open the project from Ubuntu (`code .`), run Claude Code there.
4. Keep the project **inside** the Linux disk (`~/aion/…`), not on `/mnt/c/…` — sockets and file watchers misbehave there.

**Native Windows** works for `aion-checklist` (pure Python) and most `aion-loop/bin/*.py` tools. What does not run
without porting: `aion-socket` and `mailbox/` (AF_UNIX → TCP on 127.0.0.1 or a named pipe), `runner.py`
(`fcntl` → `msvcrt.locking`), `storoj-timer.sh`/`nohup` (→ Task Scheduler), `sync/*.plist` (macOS only).
A capable agent can do this port; give it the prompt in §7.

## 5. The loop (aion-loop)

Read `aion-loop/README.md` first. In short:

1. Your canon needs a root marker `.aion-root` (see `aion-loop/data/.aion-root`, `bin/aion_root`) and the state mirror
   (`bin/aionctl bootstrap` builds it; `bin/aionctl reconcile` checks documents against disk).
2. Environment variables replace our paths:
   - `AION_ROOT` — your canon root (director, judge, watchman read it);
   - `AION_JUDGE_PYTHON` — the judge interpreter (Python 3.12 with `inspect_ai`, see `requirements-sudya.txt`); optional;
   - `AION_CHECKLIST_SOURCE` — your checklist document for `sobrat.py`;
   - `AION_GH_REPO`, `AION_CONTROL_DIR` — only if you use `sync/` (publication of the canon to GitHub).
3. Open a live Claude Code window — the executor. `python3 svyaz/src/link.py windows` must see it.
4. `nohup python3 svyaz/src/runner.py &` — the hand runs the circle: round → task in the window → the worker reports
   through the gate → judge → DONE → next. `bin/aion-loop on|off|status` pauses/resumes/shows it.

**PreToolUse hook (the guard before every action).** Add to your project's Claude Code settings
(`.claude/settings.json` in the project; never edit someone else's settings):

```json
{ "hooks": { "PreToolUse": [ { "matcher": "Edit|Write|MultiEdit|Bash",
    "hooks": [ { "type": "command", "command": "python3 /path/to/aion-kit/aion-loop/bin/gate-hook.py" } ] } ] } }
```

The hook calls `aionctl gate "<tool: action>"`; eight refusal conditions (state not confirmed, document conflict,
protected surface, unknown change, unknown critical field, known failure signature, family in diagnosis, no checkpoint
before the first mutation) → the tool call is refused with the reason. Do not install the hook before the canon is
bootstrapped — everything would be BLOCKED, by design.

**No popups at night.** Put the commands the loop runs (`python3 …`, `git …` in your project) on the agent's allow list
and keep the dangerous ones on deny. Missing permission → `bin/ochered.py add …` (owner decision queue) or a
capability request file: the item blocks, the loop continues with independent items, you answer in the morning.

## 6. Solo mode — without Codex

We use Codex as the director (writes the task packet) and as the judge (three independent readings, pass on two of three).
The law is *validator ≠ builder*: the window that built must not judge itself.

Without Codex, use **two different agent processes**:
- **executor** — your live Claude Code window (builds, reports through the gate);
- **director / judge** — a fresh non-interactive process per call: `claude -p "<packet or verdict prompt>"`.
  A fresh process has no memory of building; it reads only the evidence — that is the independence.

What to adapt: in `svyaz/src/director.py` the Codex app-server calls become `claude -p …` with the same brief/verdict text
and the same parsing (markers from `bin/markery.py`, verdict PASS/FAIL + reasons). The judge in `svyaz/sudya/` uses
`inspect_ai` + a Codex bridge; in solo mode replace it with three independent `claude -p` calls with different seeds
and a two-of-three rule.

**Simplest start (day 1): the gate only.** The agent works one item, puts evidence into `evidence/<item>/`, submits
`report PASS_CANDIDATE`. You — or a second agent window acting as director — read the evidence and `validate`.
Already this stops skipped items and unverified "done".

## 7. Prompt for your agent (copy as is)

```
Next to this project are: my product, my master document with the checklist items, and the aion-kit
(README.md and INSTALL.md — read both fully before doing anything).
Task: adapt the kit to my machine and my project without inventing anything.
1. Detect my Python (`python3 --version` / `py -3 --version`), OS and whether WSL is present. Translate every `python3`
   in scripts and docs into my command.
2. If native Windows: list the kit's Unix dependencies (AF_UNIX, fcntl, nohup, launchd, bash scripts) and propose a
   replacement for each; change one thing at a time and run that file's probes (`--proby`, tests/) after each change.
3. I have no Codex. Replace the director and the judge with `claude -p` calls (a fresh process per call) — builder and
   judge must be different processes. Never let me approve my own PASS.
4. Build opredelenie.json from my checklist items for aion-checklist (`sobrat.py`), run `proby.py`. Show me the board.
5. One change at a time; record every failure on the way in registries/otkazy-novye.jsonl with the 17 fields
   (an example record is in the file). Say "done" only after a green check, otherwise say "not verified".
6. Never write my keys, passwords or personal data into kit files; never publish anything without my word.
Start with step 1 and report what you found before changing anything.
```

## 8. Roadmap

- v0.2: code and console messages in English; state machines (`avtomaty.py`), checkpoints (`tochka.py`), capability
  requests (`zayavka.py`), promotion + observation (`prodvizhenie.py`), guardian under a supervisor.
- Windows-native port of the socket and the lock (contributions welcome — open an Issue first).
