#!/usr/bin/env python3
"""Договор формата задачи и громкий отказ (N-L1-02, CHANNEL-CONTRACT «2-ноль»).

Задача принимается только с обязательными полями: task_id и text (или «задача»).
Иначе — отказ вслух и след на диске, но задача НЕ считается принятой:

    1. НЕ СЧИТАТЬ ПРИНЯТОЙ — отказ пишется в отдельный реестр отказов, не в реестр
       задач: исправленная задача с тем же номером должна пройти.
    2. ОДИН РАЗ НА ОДИН ВИД — ключ дедупликации = task_id + отпечаток содержимого.
       Повторные круги с той же задачей не плодят записей; подправленная задача —
       новый вид, о нём говорят заново (18.09: ключ с растущим числом дал 451 повтор).
    3. СЛЕД ТУДА, КУДА СМОТРЯТ — TASK_REJECTED ложится в HANDOFF.jsonl рядом
       с расписками о приёме.

Правила — те же, что доказаны в старом мосте (most_direktora.py, заморожен);
здесь они живут в каноне и подключены к живому Директору (svyaz/src/director.py).

    from dogovor_zadachi import проверить_и_принять
    итог = проверить_и_принять(задача, handoff=Path(...), otkazy=Path(...))
    итог["принята"] -> bool; итог["след"] -> "записан" | "уже был" | None

    python3 bin/dogovor_zadachi.py --proby [--uliki <dir>]   семь проб в песочнице
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parent.parent
HANDOFF = КОРЕНЬ / "svyaz" / "state" / "HANDOFF.jsonl"
ОТКАЗЫ = КОРЕНЬ / "svyaz" / "state" / "director-otkazy.json"
ОБЯЗАТЕЛЬНЫЕ = ("task_id", "text")


def чего_не_хватает(з: dict) -> list:
    беды = []
    if not str(з.get("task_id") or "").strip():
        беды.append("нет поля task_id")
    if not str(з.get("text") or з.get("задача") or "").strip():
        беды.append("нет поля text (и нет «задача»)")
    return беды


def _отпечаток(з: dict) -> str:
    return hashlib.sha1(json.dumps(з, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def проверить_и_принять(з: dict, handoff: Path = HANDOFF, otkazy: Path = ОТКАЗЫ, actor: str = "director") -> dict:
    беды = чего_не_хватает(з)
    tid = str(з.get("task_id") or "").strip() or "(без task_id)"
    if not беды:
        return {"принята": True, "task_id": tid, "след": None, "причина": ""}
    отп = _отпечаток(з)
    ключ = f"{tid}:{отп}"
    try:
        было
    except NameError:
        pass
    try:
        было = set(json.loads(otkazy.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        было = set()
    причина = "; ".join(беды) + " — задача не принята. См. CHANNEL-CONTRACT.md «2-ноль»"
    if ключ in было:
        return {"принята": False, "task_id": tid, "след": "уже был", "причина": причина}
    строка = {"вид": "TASK_REJECTED", "task_id": tid, "когда": int(time.time()), "actor": actor,
              "причина": причина, "поля": sorted(з.keys()), "payload_hash": отп}
    handoff.parent.mkdir(parents=True, exist_ok=True)
    with handoff.open("a", encoding="utf-8") as ф:
        ф.write(json.dumps(строка, ensure_ascii=False) + "\n")
    было.add(ключ)
    врем = otkazy.with_suffix(".tmp")
    врем.write_text(json.dumps(sorted(было), ensure_ascii=False), encoding="utf-8")
    os.replace(врем, otkazy)
    return {"принята": False, "task_id": tid, "след": "записан", "причина": причина}


def _отказов(handoff: Path, tid: str) -> int:
    if not handoff.exists():
        return 0
    return sum(1 for с in handoff.read_text(encoding="utf-8").splitlines()
               if с.strip() and json.loads(с).get("вид") == "TASK_REJECTED" and json.loads(с).get("task_id") == tid)


def пробы(улики: Path = None) -> int:
    вывод = []
    def скажи(т=""):
        вывод.append(т); print(т)
    б = Path(tempfile.mkdtemp(prefix="proba-dogovora-"))
    h, o = б / "HANDOFF.jsonl", б / "director-otkazy.json"
    итоги = {}
    try:
        def шаг(н, задача, ожидание):
            и = проверить_и_принять(задача, h, o)
            tid = и["task_id"]
            скажи(f"--- проба {н}: {ожидание}")
            скажи(f"    вход: {json.dumps(задача, ensure_ascii=False)}")
            скажи(f"    вернул договор: принята={и['принята']} след={и['след']} причина={и['причина'][:70] or '—'}")
            скажи(f"    записей TASK_REJECTED для {tid}: {_отказов(h, tid)}")
            return и

        без = {"task_id": "T-PROBA-1", "created_by": "proba"}
        и1 = шаг(1, без, "без text → не принята, TASK_REJECTED записан")
        итоги["1. без text → не принята, TASK_REJECTED записан"] = (not и1["принята"]) and и1["след"] == "записан" and _отказов(h, "T-PROBA-1") == 1
        и2 = шаг(2, без, "второй круг та же задача → не принята, записи не прибавилось")
        итоги["2. второй круг та же задача → не принята, записи не прибавилось"] = (not и2["принята"]) and и2["след"] == "уже был" and _отказов(h, "T-PROBA-1") == 1
        следы = [проверить_и_принять(без, h, o)["след"] for _ in range(50)]
        скажи("--- проба 3: пятьдесят кругов подряд")
        скажи(f"    следы 50 кругов: {dict((x, следы.count(x)) for x in set(следы))}")
        скажи(f"    записей TASK_REJECTED для T-PROBA-1: {_отказов(h, 'T-PROBA-1')}")
        итоги["3. пятьдесят кругов → по-прежнему одна запись"] = _отказов(h, "T-PROBA-1") == 1 and set(следы) == {"уже был"}
        испр = dict(без, text="Сделать пробу и доложить")
        и4 = шаг(4, испр, "исправленная (text добавлен) → принята")
        итоги["4. исправленная (text добавлен) → принята"] = и4["принята"] and _отказов(h, "T-PROBA-1") == 1
        друг = {"task_id": "T-PROBA-2", "created_by": "proba"}
        и5 = шаг(5, друг, "другая задача без text → своя одна запись"); проверить_и_принять(друг, h, o)
        скажи(f"    после второго круга T-PROBA-2: записей {_отказов(h, 'T-PROBA-2')}")
        итоги["5. другая задача без text → своя одна запись"] = (not и5["принята"]) and _отказов(h, "T-PROBA-2") == 1
        иной = dict(без, note="Директор подправил, но text так и не дал")
        и6 = шаг(6, иной, "тот же номер, изменённое содержимое без text → новый вид, вторая запись"); проверить_и_принять(иной, h, o)
        скажи(f"    после второго круга изменённой: записей для T-PROBA-1 {_отказов(h, 'T-PROBA-1')}")
        итоги["6. тот же номер, изменённое содержимое без text → новый вид, вторая запись, и только одна"] = (not и6["принята"]) and и6["след"] == "записан" and _отказов(h, "T-PROBA-1") == 2
        безид = {"text": "есть текст, нет номера"}
        и7 = шаг(7, безид, "есть text, нет task_id → отказ с одним следом"); проверить_и_принять(безид, h, o)
        скажи(f"    после второго круга без номера: записей {_отказов(h, '(без task_id)')}")
        итоги["7. есть text, нет task_id → отказ с одним следом"] = (not и7["принята"]) and _отказов(h, "(без task_id)") == 1
        скажи("=== HANDOFF.jsonl (песочница) ===")
        for с in h.read_text(encoding="utf-8").splitlines():
            скажи("  " + с[:160])
        скажи("=== director-otkazy.json (песочница) ===")
        скажи("  " + o.read_text(encoding="utf-8")[:300])
        if улики:
            улики.mkdir(parents=True, exist_ok=True)
            shutil.copy2(h, улики / "HANDOFF.jsonl")
            shutil.copy2(o, улики / "director-otkazy.json")
    finally:
        shutil.rmtree(б, ignore_errors=True)
    скажи("=== ИТОГ ПРОБ ===")
    for имя, ок in итоги.items():
        скажи(f"  {'✓' if ок else '✗'} {имя}")
    всё = all(итоги.values())
    скажи(f"ПРОБ: {sum(итоги.values())} из {len(итоги)} — {'ВСЕ ВЕРНЫ' if всё else 'ЕСТЬ ОШИБКИ'}")
    if улики:
        (улики / "vyvod-prob.txt").write_text("\n".join(вывод) + "\n", encoding="utf-8")
    return 0 if всё else 1


if __name__ == "__main__":
    if "--proby" in sys.argv:
        у = Path(sys.argv[sys.argv.index("--uliki") + 1]).resolve() if "--uliki" in sys.argv else None
        sys.exit(пробы(у))
    print(__doc__)
    sys.exit(2)
