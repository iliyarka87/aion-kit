#!/usr/bin/env python3
"""Recovery after restart (N-L1-07): reconcile every task with the wire journal and the
task registry, continue what is unfinished, never lose and never re-execute.

Sources of truth (all on disk, none in memory):
    task registry     checklist/sostoyanie.json  (item, attempt_id, state, result)
    wire deliveries   svyaz/state/dostavki.jsonl (key item:attempt -> delivered / duplicate)
    queue             svyaz/state/ochered/ochered.jsonl (PENDING / PROCESSING / DONE / ...)
    channel journal   svyaz/state/zhurnal-kanala.ndjson (start/end of every move)

Four situations a restart can find, and what recovery does with each:
    IN_FLIGHT        active attempt, delivered, no report yet, within STALL
                     -> continue waiting; the key is already delivered, so NOT re-dispatched
    WAITING          message accepted in the queue but not delivered (PENDING/ERROR)
                     -> drain: deliver once (idempotent key), no second run
    DONE_NO_RECEIPT  report PASS_CANDIDATE exists, no verdict yet
                     -> continue: judge (the runner's normal path), nothing re-executed
    RECEIPT_OVERDUE  active attempt older than STALL_MIN with no report
                     -> nudge once / stop for the owner (runner rules), never re-dispatch
Anything else (no active, all delivered) -> NOTHING_TO_RECOVER.

    python3 vosstanovlenie.py                 reconcile live state, print decisions, journal them
    python3 vosstanovlenie.py --proby [--uliki <dir>]   all four situations in a sandbox
"""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
REGISTRY = ROOT / "checklist" / "sostoyanie.json"
DELIVERIES = ROOT / "svyaz" / "state" / "dostavki.jsonl"
QUEUE = ROOT / "svyaz" / "state" / "ochered" / "ochered.jsonl"
JOURNAL = ROOT / "svyaz" / "state" / "zhurnal-kanala.ndjson"
STALL_MIN = 90


def _jsonl(path: Path):
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def reconcile(registry=REGISTRY, deliveries=DELIVERIES, queue=QUEUE, now=None, stall_min=STALL_MIN) -> dict:
    """Pure: reads, decides, changes nothing. Returns decisions per task + registry snapshot."""
    now = now or time.time()
    reg = json.loads(Path(registry).read_text(encoding="utf-8"))
    delivered = {d["key"] for d in _jsonl(Path(deliveries)) if d.get("status") == "delivered"}
    q = _jsonl(Path(queue))
    waiting = [i for i in q if i.get("state") in ("PENDING", "ERROR")]
    decisions = []
    active = reg.get("active")
    snapshot = {it: {"state": p["state"], "attempts": [(a["attempt_id"], a["result"]) for a in p["attempts"]]}
                for it, p in reg["пункты"].items() if p["attempts"]}
    if active:
        p = reg["пункты"][active]
        a = p["attempts"][-1]
        key = f"{active}:{a['attempt_id']}"
        age_min = (now - a["started_at"]) / 60
        if p["state"] == "PASS_CANDIDATE":
            decisions.append({"task": active, "attempt": a["attempt_id"], "situation": "DONE_NO_RECEIPT",
                              "action": "continue: judge the candidate; nothing re-executed"})
        elif p["state"] == "ACTIVE" and age_min > stall_min:
            decisions.append({"task": active, "attempt": a["attempt_id"], "situation": "RECEIPT_OVERDUE",
                              "action": f"active {age_min:.0f} min without report: nudge once / stop for owner; never re-dispatch"})
        elif p["state"] == "ACTIVE" and key in delivered:
            decisions.append({"task": active, "attempt": a["attempt_id"], "situation": "IN_FLIGHT",
                              "action": "continue waiting; key already delivered -> not re-dispatched"})
        elif p["state"] == "ACTIVE":
            decisions.append({"task": active, "attempt": a["attempt_id"], "situation": "WAITING",
                              "action": "dispatched but not delivered: deliver once with idempotent key"})
    for i in waiting:
        decisions.append({"task": i["msg"].get("item", i["msg"].get("key")), "attempt": i["msg"].get("attempt"),
                          "situation": "WAITING", "action": f"queue {i['id']} {i['state']}: drain once (idempotent key)"})
    if not decisions:
        decisions.append({"task": None, "attempt": None, "situation": "NOTHING_TO_RECOVER", "action": "no active task, queue empty"})
    return {"decisions": decisions, "registry_snapshot": snapshot, "active": active}


def journal(phase, **fields):
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL.open("a", encoding="utf-8") as h:
        h.write(json.dumps({"t": round(time.time(), 3), "link": "wire", "move": "recovery", "phase": phase, **fields},
                           ensure_ascii=False) + "\n")


def run_live() -> int:
    journal("start", event="restart")
    r = reconcile()
    for d in r["decisions"]:
        print(f"  {d['situation']:16s} {d['task'] or '-':10s} {d['attempt'] or '-':16s} -> {d['action']}")
    journal("end", event="reconciled", decisions=r["decisions"], active=r["active"])
    return 0


def probes(evidence_dir: Path = None) -> int:
    import shutil
    import tempfile
    out = []
    def say(t=""):
        out.append(t); print(t)
    base = Path(tempfile.mkdtemp(prefix="proba-vosst-"))
    results = {}
    now = time.time()

    def registry(state, started_ago_min, result=None):
        reg = {"active": "N-PROBA-1" if state != "DONE" else None, "max_active": 1, "пункты": {
            "N-PROBA-0": {"state": "DONE", "attempts": [{"attempt_id": "A-000000000000", "started_at": now - 9000, "result": "PASS_CANDIDATE"}], "evidence": ["x"], "done_by": "director"},
            "N-PROBA-1": {"state": state, "attempts": [{"attempt_id": "A-111111111111", "started_at": now - started_ago_min * 60, "result": result}], "evidence": [], "done_by": None}}}
        p = base / f"reg-{state}-{started_ago_min}.json"; p.write_text(json.dumps(reg, ensure_ascii=False), encoding="utf-8"); return p

    def deliveries(*keys):
        p = base / "dostavki.jsonl"; p.write_text("".join(json.dumps({"t": now, "key": k, "status": "delivered"}) + "\n" for k in keys), encoding="utf-8"); return p

    def queue(*items):
        p = base / "ochered.jsonl"; p.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items), encoding="utf-8"); return p

    # 1. в полёте: ACTIVE, доставлено, отчёта нет, срок не вышел
    reg = registry("ACTIVE", 10); before = json.loads(reg.read_text(encoding="utf-8"))
    r = reconcile(reg, deliveries("N-PROBA-1:A-111111111111"), queue(), now=now)
    after = json.loads(reg.read_text(encoding="utf-8"))
    d = r["decisions"][0]
    say(f"--- 1. в полёте → {d['situation']}: {d['action']}")
    results["1. в полёте → продолжить, без повторной выдачи; реестр не изменён"] = d["situation"] == "IN_FLIGHT" and "not re-dispatched" in d["action"] and before == after

    # 2. ждущая: выдана воротами, но доставка не состоялась (ключа нет в доставках) + письмо PENDING в очереди
    reg = registry("ACTIVE", 2)
    r = reconcile(reg, deliveries(), queue({"id": "M-1", "state": "PENDING", "msg": {"key": "N-PROBA-1:A-111111111111", "item": "N-PROBA-1", "attempt": "A-111111111111", "text": "task"}}), now=now)
    sits = [x["situation"] for x in r["decisions"]]
    say(f"--- 2. ждущая → {sits}: {[x['action'] for x in r['decisions']]}")
    results["2. ждущая → доставить один раз (идемпотентный ключ)"] = sits.count("WAITING") == 2 and all("once" in x["action"] for x in r["decisions"])

    # 3. выполненная без расписки: PASS_CANDIDATE, вердикта нет
    reg = registry("PASS_CANDIDATE", 30, result="PASS_CANDIDATE")
    r = reconcile(reg, deliveries("N-PROBA-1:A-111111111111"), queue(), now=now)
    d = r["decisions"][0]
    say(f"--- 3. выполненная без расписки → {d['situation']}: {d['action']}")
    results["3. выполнена без расписки → судить, не исполнять заново"] = d["situation"] == "DONE_NO_RECEIPT" and "nothing re-executed" in d["action"]

    # 4. просроченная расписка: ACTIVE дольше STALL
    reg = registry("ACTIVE", 120)
    r = reconcile(reg, deliveries("N-PROBA-1:A-111111111111"), queue(), now=now)
    d = r["decisions"][0]
    say(f"--- 4. просроченная → {d['situation']}: {d['action']}")
    results["4. просрочена → напомнить/стоп владельцу, никогда не выдавать заново"] = d["situation"] == "RECEIPT_OVERDUE" and "never re-dispatch" in d["action"]

    # 5. идентификаторы и статусы неизменны во всех четырёх случаях (reconcile ничего не пишет)
    results["5. реестр до и после сверки: идентификаторы и статусы неизменны"] = True
    for state, mins, res in (("ACTIVE", 10, None), ("ACTIVE", 2, None), ("PASS_CANDIDATE", 30, "PASS_CANDIDATE"), ("ACTIVE", 120, None)):
        reg = registry(state, mins, res); b = reg.read_text(encoding="utf-8")
        reconcile(reg, deliveries("N-PROBA-1:A-111111111111"), queue(), now=now)
        results["5. реестр до и после сверки: идентификаторы и статусы неизменны"] &= (reg.read_text(encoding="utf-8") == b)
    say("=== ИТОГ ПРОБ ===")
    for k, v in results.items():
        say(f"  {'✓' if v else '✗'} {k}")
    ok = all(results.values())
    say(f"ПРОБ: {sum(bool(v) for v in results.values())} из {len(results)} — {'ВСЕ ВЕРНЫ' if ok else 'ЕСТЬ ОШИБКИ'}")
    if evidence_dir:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / "vyvod-prob.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    shutil.rmtree(base, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "--proby":
        d = Path(a[a.index("--uliki") + 1]).resolve() if "--uliki" in a else None
        sys.exit(probes(d))
    sys.exit(run_live())
