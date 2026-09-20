"""Director side of the loop: decide, dispatch, judge.

The director reads the checklist board, picks the one item the gate offers,
writes a short brief for the executor, hands it over through the local link,
and later judges the delivered evidence against the item's acceptance.

The director never builds. The executor never approves itself. Every state
change goes through the checklist gate, which is the only thing allowed to
write DONE.

    python3 director.py decide    only the brief, nothing is sent
    python3 director.py round     dispatch the next item to the executor
    python3 director.py judge     judge the candidate and record the verdict
"""
import os
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("AION_ROOT", ".")).resolve()   # корень канона: AION_ROOT
CHECKLIST = ROOT / "checklist"
LINK = Path(__file__).with_name("link.py")
LEDGER = ROOT / "svyaz" / "letopis-svyazi.ndjson"
CODEX = "/Applications/ChatGPT.app/Contents/Resources/codex"
CODEX_TIMEOUT = 420


def record(kind, **fields):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    entry = {"at": round(time.time(), 1), "kind": kind, **fields}
    with LEDGER.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def gate(*args):
    """Run the checklist gate. It owns every rule; this module owns none."""
    done = subprocess.run([sys.executable, "vorota.py", *args], cwd=CHECKLIST,
                          capture_output=True, text=True)
    return done.returncode, ((done.stdout or "") + (done.stderr or "")).strip()


def ask_codex(question: str) -> str:
    """One read-only Codex turn over the local app-server. No network hop."""
    proc = subprocess.Popen([CODEX, "app-server", "--listen", "stdio://"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, bufsize=1)
    started, counter, chunks = time.time(), [0], []

    def call(method, params):
        counter[0] += 1
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": counter[0],
                                     "method": method, "params": params},
                                    ensure_ascii=False) + "\n")
        proc.stdin.flush()
        return counter[0]

    def until(predicate):
        while time.time() - started < CODEX_TIMEOUT:
            line = proc.stdout.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except Exception:
                continue
            if predicate(message):
                return message
        return None

    try:
        rid = call("initialize", {"clientInfo": {"name": "aion-director",
                                                 "title": "Director",
                                                 "version": "1"}})
        until(lambda m: m.get("id") == rid)
        rid = call("thread/start", {"cwd": str(ROOT), "sandbox": "read-only",
                                    "approvalPolicy": "never", "ephemeral": True})
        answer = until(lambda m: m.get("id") == rid)
        thread = (((answer or {}).get("result") or {}).get("thread") or {}).get("id")
        if not thread:
            return ""
        rid = call("turn/start", {"threadId": thread,
                                  "input": [{"type": "text", "text": question}]})

        def finished(message):
            method = message.get("method", "")
            if method == "item/agentMessage/delta":
                chunks.append((message.get("params") or {}).get("delta", ""))
            return method.startswith("turn/completed")
        until(finished)
    finally:
        try:
            proc.stdin.close()
            proc.terminate()
            proc.wait(timeout=8)
        except Exception:
            proc.kill()
    return "".join(chunks).strip()


def decide():
    """Ask the gate for the next item, then ask Codex to brief the executor."""
    code, item = gate("next-ready")
    if code != 0 or not item.startswith("N-"):
        return None, None, f"gate offered no item: {item}"
    spec = json.loads((CHECKLIST / "opredelenie.json").read_text(encoding="utf-8"))
    entry = spec["пункты"][item]
    question = (
        "You are the DIRECTOR of the AION project. You do NOT build. "
        "You set the task for the executor.\n"
        "Read the checklist item and write a short brief: what to do, what "
        "counts as acceptance, which evidence files are required.\n"
        "At most 12 lines. Write in Russian. Do not perform anything yourself.\n\n"
        f"ITEM: {item} - {entry['имя']}\n"
        f"OBJECTIVE: {entry['objective']}\n"
        f"ACCEPTANCE: {entry['acceptance']}\n"
        f"EVIDENCE: {entry['required_evidence']}\n"
        f"OUT OF SCOPE: {entry.get('non_scope', '')[:300]}\n"
        f"RISK: {entry['risk']}\n")
    return item, ask_codex(question), ""


def round_trip():
    code, board = gate("status")
    print(board.splitlines()[0])
    item, brief, problem = decide()
    if not item:
        print(f"STOP: {problem}")
        return 1
    print(f"director picked: {item}")
    # task contract (N-L1-02): a task without text is rejected out loud, leaves one
    # durable trace per kind, and is never counted as accepted.
    sys.path.insert(0, str(ROOT / "bin"))
    from dogovor_zadachi import проверить_и_принять  # noqa: E402
    verdict = проверить_и_принять({"task_id": item, "text": brief or "", "created_by": "codex-director"},
                                  actor="director.py")
    if not verdict["принята"]:
        record("TASK_REJECTED", item=item, reason=verdict["причина"], trace=verdict["след"])
        print(f"REJECTED: {verdict['причина']} (след: {verdict['след']})")
        return 1
    record("BRIEF", item=item, text=brief[:2000])

    code, said = gate("dispatch", item, "--by", "director")
    if code != 0:
        print(f"STOP: gate refused dispatch - {said}")
        return 1
    print(f"  {said}")

    from markery import declare  # noqa: E402  same dictionary as the wire (N-L1-03)
    message = (f"TASK FROM DIRECTOR - item {item}\n\n{brief}\n\n{declare(item)}\n\n"
               "When done, report through the gate:\n"
               f"  cd {CHECKLIST} && python3 vorota.py report PASS_CANDIDATE "
               "--by worker --evidence <file> ...\n"
               "Do not approve yourself: the director does that.")
    import re as _re
    attempt = (_re.search(r"A-[0-9a-f]{12}", said) or [None])
    attempt = attempt.group(0) if attempt else "A-unknown"
    message = message.replace(f"TASK FROM DIRECTOR - item {item}\n", f"TASK FROM DIRECTOR - item {item} (attempt {attempt})\n", 1)
    # durable queue with explicit states and a dead letter (N-L1-06): the message is
    # accepted on disk first, then delivered; a failure becomes ERROR/DEAD_LETTER, never a loss
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from mailqueue import Queue, DELIVERED  # noqa: E402
    queue = Queue()
    entry = queue.enqueue({"key": f"{item}:{attempt}", "text": message, "item": item, "attempt": attempt})
    counts = queue.drain()
    state_now = next((i["state"] for i in queue._load() if i["id"] == entry["id"]), entry["state"])
    print(f"  to executor: queue {entry['id']} -> {state_now}  {counts}")
    if state_now != DELIVERED:
        record("DELIVERY_NOT_DONE", item=item, attempt=attempt, state=state_now, reason=entry.get("reason", ""))
        print(f"STOP: delivery not done ({state_now}); see mailqueue.py dead")
        return 1
    record("DISPATCHED", item=item, attempt=attempt)
    print("\nWith the executor. When it reports: python3 director.py judge")
    return 0


JUDGE_PYTHON = Path(os.environ.get("AION_JUDGE_PYTHON", "python3.12"))   # окружение судьи (inspect_ai)
JUDGE = Path(__file__).resolve().parent.parent / "sudya" / "sudit.py"


def three_votes(item: str, evidence: list) -> dict:
    """Ask the three-reading judge. It lives on its own interpreter.

    One reading of the same evidence gave PASS one day and FAIL the next.
    The judge behind this call reads three times in three separate threads
    and passes only when at least two agree. It decides nothing about the
    board — it speaks, and the gate writes.
    """
    if not JUDGE_PYTHON.exists():
        return {"вердикт": "НЕ СОСТОЯЛСЯ",
                "почему": f"judge interpreter missing: {JUDGE_PYTHON}"}
    def is_file(e):
        try:
            return Path(e).is_file()
        except OSError:            # a long claim is not a path; never crash the judge on it
            return False
    files = [e for e in evidence if is_file(e)]
    claims = [e for e in evidence if not is_file(e)]
    args = [str(JUDGE_PYTHON), str(JUDGE), item]
    if files:
        args += ["--uliki", *files]
    if claims:
        args += ["--tekst", "\n".join(claims)]
    done = subprocess.run(args, capture_output=True, text=True, timeout=900)
    try:
        return json.loads(done.stdout)
    except ValueError:
        return {"вердикт": "НЕ СОСТОЯЛСЯ",
                "почему": (done.stderr or done.stdout).strip()[-400:]}



def execute_probes(item: str, evidence: list) -> dict:
    """The judge runs the probes itself and writes their real output to a file the readers get."""
    import re as _re
    sys.path.insert(0, str(ROOT / "bin"))
    runs = []
    try:
        from sled import ИНВАРИАНТЫ_ПО_ПУНКТАМ  # noqa: E402
        inv = ИНВАРИАНТЫ_ПО_ПУНКТАМ.get(item)
    except Exception:
        inv = None
    cmds = []
    if inv:
        cmds.append((inv[1], inv[2]))
    paths = [e for e in evidence if e.startswith(str(ROOT))]
    rel = [str(Path(e).relative_to(ROOT)) for e in paths if Path(e).exists()]
    for cmd, expected in cmds:
        t0 = time.time()
        r = subprocess.run(cmd.split(), capture_output=True, text=True, cwd=str(ROOT), timeout=900)
        out = r.stdout + r.stderr
        ok = r.returncode == 0 and (expected in out)
        line = next((l for l in reversed(out.splitlines()) if l.strip()), "")
        runs.append({"layer": "invariant", "cmd": cmd, "ok": ok, "rc": r.returncode, "seconds": round(time.time() - t0, 1), "line": line[:120], "expected": expected})
    reg = subprocess.run([sys.executable, str(ROOT / "bin" / "regressii.py"), "run", "--type", "code", "--paths", *(rel or ["evidence/"])],
                         capture_output=True, text=True, cwd=str(ROOT), timeout=1200)
    reg_out = reg.stdout + reg.stderr
    reg_ok = reg.returncode == 0 and "ИТОГ: PASS" in reg_out
    reg_line = next((l for l in reversed(reg_out.splitlines()) if l.startswith("ИТОГ")), "")
    runs.append({"layer": "regressions", "cmd": "bin/regressii.py run --type code", "ok": reg_ok, "rc": reg.returncode, "seconds": None, "line": reg_line[:120]})
    ok = all(r["ok"] for r in runs)
    folder = ROOT / "svyaz" / "state" / "sudya-proby"
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / f"{item}-{int(time.time())}.txt"
    f.write_text("=== СУДЬЯ-ИСПОЛНИТЕЛЬ: пробы запущены самим судьёй перед чтением улик ===\n"
                 + "\n".join(f"[{'ok ' if r['ok'] else 'FAIL'}] {r['layer']:12s} {r['cmd']} → {r['line']}" for r in runs)
                 + f"\nИТОГ: {'ВСЕ ЗЕЛЁНЫЕ' if ok else 'ЕСТЬ КРАСНЫЕ — вердикт FAIL без чтения'}\n\n--- регрессии подробно ---\n" + reg_out[-3000:],
                 encoding="utf-8")
    return {"ok": ok, "runs": runs, "file": str(f), "summary": {"ok": ok, "runs": len(runs), "failed": [r["cmd"] for r in runs if not r["ok"]]}}


def judge():
    """Judge the candidate. Only the gate writes DONE, and only on PASS."""
    state = json.loads((CHECKLIST / "sostoyanie.json").read_text(encoding="utf-8"))
    item = state.get("active")
    if not item or state["пункты"][item]["state"] != "PASS_CANDIDATE":
        current = state["пункты"][item]["state"] if item else "-"
        print(f"nothing to judge: active={item}, state={current}")
        return 1
    attempt = state["пункты"][item]["attempts"][-1]
    evidence = attempt.get("evidence", [])

    # the judge EXECUTES before it reads (owner, 20.09: a reader can be talked into a PASS):
    # 1) the item's invariant probe, 2) layered regressions for the evidence paths.
    # Red probes = FAIL, and Codex is not even asked. Green probes go to the judge as evidence.
    executed = execute_probes(item, evidence)
    if not executed["ok"]:
        verdict = {"вердикт": "FAIL", "голоса": ["FAIL", "FAIL", "FAIL"],
                   "причины": [f"судья-исполнитель: {r['cmd']} → {r['line'] or 'код ' + str(r['rc'])}" for r in executed["runs"] if not r["ok"]],
                   "личности": {"проверяющий": {"роль": "verifier-executor", "модель": "пробы запущены самим судьёй (без Codex)"}}}
    else:
        evidence = list(evidence) + [executed["file"]]
        verdict = three_votes(item, evidence)
    record("VERDICT", item=item, verdict=verdict.get("вердикт"), executed=executed["summary"],
           votes=verdict.get("голоса"), reasons=verdict.get("причины"),
           identities=verdict.get("личности"), recorded_by="director.py (судья → Директор → ворота)")
    meta = ROOT / "svyaz" / "state" / "verdikty"
    meta.mkdir(parents=True, exist_ok=True)
    (meta / f"{item}-{attempt['attempt_id']}-{int(time.time())}.json").write_text(
        json.dumps({"item": item, "attempt": attempt["attempt_id"], "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "verdict": verdict.get("вердикт"), "votes": verdict.get("голоса"), "identities": verdict.get("личности"),
                    "written_by": "director.py", "builder_may_write": False}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"verdict: {verdict.get('вердикт')}  votes: {verdict.get('голоса')}")
    for reason in verdict.get("причины") or []:
        print(f"  - {reason[:200]}")
    if verdict.get("почему"):
        print(f"  ! {verdict['почему']}")

    if verdict.get("вердикт") != "PASS":
        print("\nnot approved")
        return 1

    votes = verdict.get("голоса") or []
    stamp = f"director verdict: PASS ({votes.count('PASS')} of {len(votes)} votes)"
    args = []
    for item_evidence in evidence + [stamp]:
        args += ["--evidence", item_evidence]
    code, said = gate("validate", item, "--by", "director", *args)
    print(f"\n{said}")
    return 0 if code == 0 else 1


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "round"
    actions = {"round": round_trip,
               "decide": lambda: (print(decide()[1] or "-"), 0)[1],
               "judge": judge}
    sys.exit(actions.get(command, lambda: (print(__doc__), 2)[1])())
