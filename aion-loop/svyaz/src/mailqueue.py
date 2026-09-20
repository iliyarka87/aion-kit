#!/usr/bin/env python3
"""Durable message queue for the wire with explicit states and a visible dead letter (N-L1-06).

Every message the director (or the runner) wants delivered to the executor window
goes through here, on disk, so nothing accepted is ever lost and nothing
unreadable ever vanishes silently.

States (state/ochered/ochered.jsonl, one record per message, rewritten atomically):
    PENDING      accepted, waiting for delivery
    PROCESSING   being delivered right now
    DONE         delivered to the window (idempotent key honoured by link.send)
    ERROR        delivery failed, will be retried (up to MAX_RETRIES)
    DEAD_LETTER  taken out of the flow, kept for a human: unparseable message,
                 delivery failed MAX_RETRIES times, stuck in PROCESSING past
                 STUCK_SEC, or refused because the queue was full (overflow)
Transitions go to state/ochered/perehody.ndjson: {t, id, from, to, reason}.

Backpressure: the queue holds at most CAPACITY pending messages. Beyond that a
new message is NOT accepted into the flow — it becomes a DEAD_LETTER with reason
"overflow", visible and with its full payload, and the executor keeps running.
Accepted messages are never dropped by overflow.

    python3 mailqueue.py enqueue '<json>'        put a message in (json: {"key":..,"text":..})
    python3 mailqueue.py drain                   deliver pending messages (one pass)
    python3 mailqueue.py status                  counts per state
    python3 mailqueue.py dead                    list dead letters with reasons
    python3 mailqueue.py --proby [--uliki <dir>] states, overflow, unparseable, stuck, retry
"""
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE_DIR = HERE.parent / "state" / "ochered"
CAPACITY = 20
MAX_RETRIES = 3
STUCK_SEC = 900
STATES = ("PENDING", "PROCESSING", "DONE", "ERROR", "DEAD_LETTER")
DELIVERED = STATES[2]   # the queue's own "delivered" state name; the director compares against this constant
REQUIRED = ("key", "text")


class Queue:
    def __init__(self, state_dir: Path = STATE_DIR, capacity: int = CAPACITY,
                 max_retries: int = MAX_RETRIES, stuck_sec: int = STUCK_SEC, deliver=None):
        self.dir = Path(state_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.file = self.dir / "ochered.jsonl"
        self.transitions = self.dir / "perehody.ndjson"
        self.capacity, self.max_retries, self.stuck_sec = capacity, max_retries, stuck_sec
        self.deliver = deliver or self._deliver_via_link

    # ---- storage ----
    def _load(self):
        if not self.file.exists():
            return []
        return [json.loads(line) for line in self.file.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _save(self, items):
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items), encoding="utf-8")
        os.replace(tmp, self.file)

    def _move(self, item, to, reason=""):
        with self.transitions.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"t": round(time.time(), 3), "id": item["id"], "from": item.get("state"),
                                     "to": to, "reason": reason}, ensure_ascii=False) + "\n")
        item["state"] = to
        item["updated"] = round(time.time(), 3)
        if reason:
            item["reason"] = reason

    # ---- API ----
    def enqueue(self, raw) -> dict:
        """Accept a message. Unparseable or over capacity -> DEAD_LETTER, never an exception upward."""
        items = self._load()
        item = {"id": f"M-{int(time.time() * 1000)}-{len(items) + 1:04d}", "state": None,
                "accepted": round(time.time(), 3), "tries": 0}
        try:
            msg = raw if isinstance(raw, dict) else json.loads(raw)
            if not isinstance(msg, dict):
                raise ValueError("not an object")
            missing = [f for f in REQUIRED if not str(msg.get(f) or "").strip()]
            if missing:
                raise ValueError("missing fields: " + ", ".join(missing))
            item["msg"] = msg
        except (ValueError, TypeError) as error:
            item["raw"] = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
            self._move(item, "DEAD_LETTER", f"unparseable: {error}")
            items.append(item); self._save(items)
            return item
        pending = sum(1 for i in items if i["state"] in ("PENDING", "PROCESSING", "ERROR"))
        if pending >= self.capacity:
            self._move(item, "DEAD_LETTER", f"overflow: {pending} in flight >= capacity {self.capacity}")
            items.append(item); self._save(items)
            return item
        self._move(item, "PENDING", "accepted")
        items.append(item); self._save(items)
        return item

    def drain(self) -> dict:
        """One delivery pass. Never raises: a broken message becomes ERROR/DEAD_LETTER, the loop goes on."""
        items = self._load()
        now = time.time()
        counts = {"delivered": 0, "error": 0, "dead": 0, "stuck": 0}
        for item in items:
            if item["state"] == "PROCESSING" and now - item.get("updated", now) > self.stuck_sec:
                self._move(item, "DEAD_LETTER", f"stuck in PROCESSING > {self.stuck_sec}s")
                counts["stuck"] += 1
        self._save(items)
        for item in items:
            if item["state"] not in ("PENDING", "ERROR"):
                continue
            self._move(item, "PROCESSING", "delivering")
            self._save(items)
            item["tries"] += 1
            try:
                ok, detail = self.deliver(item["msg"])
            except Exception as error:  # noqa: BLE001 - the executor must not fall over a bad message
                ok, detail = False, f"{type(error).__name__}: {error}"
            if ok:
                self._move(item, "DONE", detail[:120]); counts["delivered"] += 1
            elif item["tries"] >= self.max_retries:
                self._move(item, "DEAD_LETTER", f"delivery failed {item['tries']} times: {detail[:120]}"); counts["dead"] += 1
            else:
                self._move(item, "ERROR", f"try {item['tries']}: {detail[:120]}"); counts["error"] += 1
            self._save(items)
        return counts

    def status(self) -> dict:
        items = self._load()
        return {s: sum(1 for i in items if i["state"] == s) for s in STATES}

    def dead_letters(self) -> list:
        return [{"id": i["id"], "reason": i.get("reason"), "accepted": i["accepted"], "tries": i.get("tries", 0),
                 "payload": i.get("msg") or i.get("raw")} for i in self._load() if i["state"] == "DEAD_LETTER"]

    # ---- default delivery ----
    @staticmethod
    def _deliver_via_link(msg):
        import subprocess
        done = subprocess.run([sys.executable, str(HERE / "link.py"), "send", msg["text"], "--key", msg["key"]],
                              capture_output=True, text=True, timeout=60)
        out = (done.stdout or done.stderr).strip()
        if done.returncode == 4:
            return True, "repeat suppressed by link (idempotent key)"
        return done.returncode == 0, out


def probes(evidence_dir: Path = None) -> int:
    import shutil
    import tempfile
    out = []
    def say(t=""):
        out.append(t); print(t)
    base = Path(tempfile.mkdtemp(prefix="proba-ocheredi-"))
    results = {}
    failing = {"n": 0}
    def flaky(msg):
        # first message with key "flaky" fails twice, then succeeds; key "dead" always fails
        if msg["key"] == "dead":
            return False, "window refused"
        if msg["key"] == "flaky":
            failing["n"] += 1
            return (failing["n"] >= 3), f"try {failing['n']}"
        return True, "delivered (stub)"
    q = Queue(base / "ochered", capacity=3, max_retries=3, stuck_sec=1, deliver=flaky)

    a = q.enqueue({"key": "ok-1", "text": "обычное письмо"})
    results["1. принято → PENDING"] = a["state"] == "PENDING"
    b = q.enqueue("это не json {{{")
    results["2. неразбираемое → DEAD_LETTER с причиной, не исчезло"] = b["state"] == "DEAD_LETTER" and "unparseable" in b["reason"] and b.get("raw")
    c = q.enqueue({"text": "нет ключа"})
    results["3. без обязательного поля → DEAD_LETTER (missing fields)"] = c["state"] == "DEAD_LETTER" and "missing" in c["reason"]
    q.enqueue({"key": "ok-2", "text": "второе"}); q.enqueue({"key": "ok-3", "text": "третье"})
    d = q.enqueue({"key": "ok-4", "text": "четвёртое — сверх ёмкости 3"})
    st = q.status()
    results["4. переполнение: 4-е письмо → DEAD_LETTER(overflow), три принятых целы"] = d["state"] == "DEAD_LETTER" and "overflow" in d["reason"] and st["PENDING"] == 3
    say(f"--- после приёма: {st}")
    counts = q.drain()
    say(f"--- drain 1: {counts}; состояния {q.status()}")
    results["5. drain доставил принятые, исполнитель не упал"] = counts["delivered"] == 3 and q.status()["DONE"] == 3
    q.enqueue({"key": "flaky", "text": "мигающая доставка"}); q.enqueue({"key": "dead", "text": "всегда отказ"})
    c1 = q.drain(); c2 = q.drain(); c3 = q.drain()
    say(f"--- повторная обработка ошибок: drain 2 {c1}, drain 3 {c2}, drain 4 {c3}; состояния {q.status()}")
    results["6. ERROR повторяется до успеха (flaky → DONE на 3-й раз)"] = q.status()["DONE"] == 4
    def key_of(dl):
        return dl["payload"].get("key") if isinstance(dl["payload"], dict) else None
    results["7. после MAX_RETRIES → DEAD_LETTER (dead)"] = any(key_of(dl) == "dead" and "failed 3 times" in dl["reason"] for dl in q.dead_letters())
    # застрявшее письмо: PROCESSING дольше stuck_sec
    items = q._load(); s = q.enqueue({"key": "stuck", "text": "застряну"}); items = q._load()
    for i in items:
        if i["id"] == s["id"]:
            q._move(i, "PROCESSING", "имитация зависшей доставки"); i["updated"] = time.time() - 5
    q._save(items); q.drain()
    results["8. застрявшее в PROCESSING → DEAD_LETTER (stuck)"] = any(key_of(dl) == "stuck" and "stuck" in dl["reason"] for dl in q.dead_letters())
    say("--- мёртвые письма (отдельный список с данными для разбора):")
    for dl in q.dead_letters():
        say("    " + json.dumps(dl, ensure_ascii=False)[:170])
    say("--- переходы (state/ochered/perehody.ndjson), первые 12:")
    for line in q.transitions.read_text(encoding="utf-8").splitlines()[:12]:
        say("    " + line[:150])
    say("=== ИТОГ ПРОБ ===")
    for name, ok in results.items():
        say(f"  {'✓' if ok else '✗'} {name}")
    all_ok = all(results.values())
    say(f"ПРОБ: {sum(bool(v) for v in results.values())} из {len(results)} — {'ВСЕ ВЕРНЫ' if all_ok else 'ЕСТЬ ОШИБКИ'}")
    if evidence_dir:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / "vyvod-prob.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
        shutil.copy2(q.file, evidence_dir / "sostoyaniya-ocheredi.jsonl")
        shutil.copy2(q.transitions, evidence_dir / "perehody.ndjson")
        (evidence_dir / "myortvye-pisma.json").write_text(json.dumps(q.dead_letters(), ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.rmtree(base, ignore_errors=True)
    return 0 if all_ok else 1


def main(argv):
    if not argv:
        print(__doc__); return 2
    if argv[0] == "--proby":
        d = Path(argv[argv.index("--uliki") + 1]).resolve() if "--uliki" in argv else None
        return probes(d)
    q = Queue()
    if argv[0] == "enqueue":
        item = q.enqueue(argv[1]); print(f"{item['id']} -> {item['state']} ({item.get('reason', '')})"); return 0
    if argv[0] == "drain":
        print(q.drain()); return 0
    if argv[0] == "status":
        print(q.status()); return 0
    if argv[0] == "dead":
        for dl in q.dead_letters():
            print(json.dumps(dl, ensure_ascii=False))
        return 0
    print(__doc__); return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
