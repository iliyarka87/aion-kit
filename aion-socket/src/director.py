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
    if not brief:
        print("STOP: Codex returned no brief")
        return 1
    record("BRIEF", item=item, text=brief[:2000])

    code, said = gate("dispatch", item, "--by", "director")
    if code != 0:
        print(f"STOP: gate refused dispatch - {said}")
        return 1
    print(f"  {said}")

    message = (f"TASK FROM DIRECTOR - item {item}\n\n{brief}\n\n"
               "When done, report through the gate:\n"
               f"  cd {CHECKLIST} && python3 vorota.py report PASS_CANDIDATE "
               "--by worker --evidence <file> ...\n"
               "Do not approve yourself: the director does that.")
    done = subprocess.run([sys.executable, str(LINK), "send", message],
                          capture_output=True, text=True)
    print(f"  to executor: {(done.stdout or done.stderr).strip()[:100]}")
    record("DISPATCHED", item=item)
    print("\nWith the executor. When it reports: python3 director.py judge")
    return 0


JUDGE_PYTHON = Path(os.environ.get("AION_JUDGE_PYTHON", "python3.12"))
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
    files = [e for e in evidence if Path(e).is_file()]
    claims = [e for e in evidence if not Path(e).is_file()]
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

    verdict = three_votes(item, evidence)
    record("VERDICT", item=item, verdict=verdict.get("вердикт"),
           votes=verdict.get("голоса"), reasons=verdict.get("причины"))
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
