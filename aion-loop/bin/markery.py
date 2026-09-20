#!/usr/bin/env python3
"""Единый словарь терминальных маркеров (N-L1-03) — один для Директора и провода.

Маркер — последняя строка отчёта исполнителя, по которой канал закрывает задачу:

    ИМЯ_ОКОНЧАНИЕ ЗАДАЧА        например  ROUTER_PASS N-L0-04   или  JOURNAL_WATCH_BLOCKED T-PETLYA-2-1-JOURNAL-WATCH-01

Словарь окончаний (только эти, ровно так, заглавными):
    успех:      PASS, DONE, OK
    не успех:   FAIL, FAILED, BLOCKED
Правила распознавания — одни на обе стороны, обе берут их отсюда:
    1. имя: [A-Z][A-Z0-9_]{3,}, окончание через «_», затем пробел и номер задачи (T-… или N-…);
    2. номер совпадает с задачей ПОСИМВОЛЬНО (…-09 ≠ …-09-B);
    3. окончание — только из словаря; READY, SUCCESS, ГОТОВО и строчные — не маркер;
    4. если Директор объявил маркеры в тексте задачи, объявленные распознаются как объявленные,
       но любое окончание из словаря с точным номером тоже распознаётся: честный BLOCKED
       нельзя заткнуть объявлением одного PASS (ловушка 18.09, T-REMOVE-CLAUDE-FROM-LOOP-10);
    5. неизвестное или ошибочное окончание — ВИДИМЫЙ ОТКАЗ с причиной и кодом 3, никогда молча;
    6. маркера нет — ВИДИМО «NONE», задача не закрывается.

    python3 bin/markery.py declare <ЗАДАЧА> [ИМЯ]      строка объявления для брифа
    python3 bin/markery.py parse <ЗАДАЧА> < отчёт      разобрать отчёт со stdin
    python3 bin/markery.py --proby [--uliki <dir>]     набор примеров: успешные, неизвестные, ошибочные
"""
import json
import re
import sys
from pathlib import Path

УСПЕХ = ("PASS", "DONE", "OK")
НЕ_УСПЕХ = ("FAIL", "FAILED", "BLOCKED")
СЛОВАРЬ = УСПЕХ + НЕ_УСПЕХ
_ИМЯ = r"[A-Z][A-Z0-9_]{3,}?"
_ЗАДАЧА = r"[TN]-[A-Z0-9_-]+"
# любая строка вида ИМЯ_ЧТО-ТО ЗАДАЧА — кандидат; окончание проверяется отдельно, чтобы отказ был видимым
КАНДИДАТ = re.compile(rf"(?m)^\s*({_ИМЯ})_([A-Za-zА-Яа-я0-9]+)\s+({_ЗАДАЧА})\s*$")


def declare(task_id: str, name: str = None) -> str:
    """Что Директор пишет в брифе — из того же словаря."""
    имя = (name or re.sub(r"[^A-Z0-9]", "_", task_id.upper()).strip("_"))
    return (f"Терминальные маркеры (последней строкой ответа, дословно): "
            f"успех — {имя}_PASS {task_id}; отказ — {имя}_BLOCKED {task_id} или {имя}_FAIL {task_id}.")


def declared_in(task_text: str) -> list:
    """Маркеры, объявленные в тексте задачи: пары (ИМЯ_ОКОНЧАНИЕ, ЗАДАЧА)."""
    return [(f"{m.group(1)}_{m.group(2)}", m.group(3))
            for m in re.finditer(rf"({_ИМЯ})_({'|'.join(СЛОВАРЬ)})\s+({_ЗАДАЧА})", task_text)]


def parse(reply: str, task_id: str, task_text: str = "") -> dict:
    """Разбор отчёта. Всегда возвращает видимый итог; никогда не молчит."""
    объявлены = declared_in(task_text)
    кандидаты = list(КАНДИДАТ.finditer(reply))
    if not кандидаты:
        return {"status": "NONE", "verdict": None, "marker": None, "reason": "маркера нет — задача не закрыта"}
    m = кандидаты[-1]                       # последняя строка-маркер решает
    имя, окончание, номер = m.group(1), m.group(2), m.group(3)
    маркер = f"{имя}_{окончание} {номер}"
    if окончание not in СЛОВАРЬ:
        близко = окончание.upper() if окончание.upper() in СЛОВАРЬ else None
        return {"status": "UNKNOWN_ENDING", "verdict": None, "marker": маркер,
                "reason": f"окончание «{окончание}» не из словаря {list(СЛОВАРЬ)}"
                          + (f" (вы имели в виду {близко}? заглавными)" if близко else "")}
    if номер != task_id:
        return {"status": "WRONG_TASK_ID", "verdict": None, "marker": маркер,
                "reason": f"номер «{номер}» ≠ задача «{task_id}» (посимвольно)"}
    вид = "success" if окончание in УСПЕХ else "failure"
    объявлен = (f"{имя}_{окончание}", номер) in объявлены
    return {"status": "FOUND", "verdict": вид, "marker": маркер, "declared": объявлен,
            "reason": ("объявленный Директором маркер" if объявлен else
                       "маркер из словаря с точным номером" + (" — не объявлен, но честный итог принимается (правило 4)" if объявлены else ""))}


def show(итог: dict) -> int:
    if итог["status"] == "FOUND":
        print(f"FOUND   {итог['marker']}  → {итог['verdict']}  ({итог['reason']})")
        return 0
    print(f"ОТКАЗ   {итог['status']}: {итог['reason']}" + (f"  [{итог['marker']}]" if итог.get("marker") else ""))
    return 3


ПРИМЕРЫ = [
    ("успешный из текста задачи", "N-L0-04", "Задача… " + declare("N-L0-04", "ROUTER"), "сделано\nROUTER_PASS N-L0-04", "FOUND", "success"),
    ("объявленный отказ", "N-L0-04", declare("N-L0-04", "ROUTER"), "не вышло\nROUTER_BLOCKED N-L0-04", "FOUND", "failure"),
    ("честный BLOCKED, когда объявлен только PASS", "T-REMOVE-CLAUDE-FROM-LOOP-10",
     "Success marker LOOP_PASS T-REMOVE-CLAUDE-FROM-LOOP-10", "правда: нельзя\nLOOP_BLOCKED T-REMOVE-CLAUDE-FROM-LOOP-10", "FOUND", "failure"),
    ("неизвестное окончание READY", "N-L0-05", "", "готово\nSVERKA_READY N-L0-05", "UNKNOWN_ENDING", None),
    ("строчные буквы", "N-L0-05", "", "SVERKA_pass N-L0-05", "UNKNOWN_ENDING", None),
    ("не тот номер (…-09-B vs …-09)", "T-CODEX-HOME-09-B", "", "GATE_PASS T-CODEX-HOME-09", "WRONG_TASK_ID", None),
    ("маркера нет", "N-L0-06", "", "всё сделал, честно", "NONE", None),
    ("два маркера — решает последний", "N-L0-07", "", "VLAST_PASS N-L0-07\nпотом передумала\nVLAST_FAIL N-L0-07", "FOUND", "failure"),
    ("маркер внутри строки, не отдельной строкой", "N-L0-07", "", "в конце я написала VLAST_PASS N-L0-07 и ушла", "NONE", None),
    ("DONE и OK тоже успех", "T-X-1", "", "PROBA_DONE T-X-1", "FOUND", "success"),
    ("имя короче четырёх знаков (X_OK) — не маркер, видимо NONE", "T-X-1", "", "X_OK T-X-1", "NONE", None),
]


def пробы(улики: Path = None) -> int:
    вывод = []
    def скажи(т=""):
        вывод.append(т); print(т)
    итоги = []
    скажи(f"словарь: успех {list(УСПЕХ)}, не успех {list(НЕ_УСПЕХ)}")
    скажи(f"объявление Директора (пример): {declare('N-L0-04', 'ROUTER')}")
    скажи("")
    for имя, tid, текст, ответ, ждём_статус, ждём_вид in ПРИМЕРЫ:
        и = parse(ответ, tid, текст)
        ок = и["status"] == ждём_статус and (ждём_вид is None or и.get("verdict") == ждём_вид)
        итоги.append(ок)
        скажи(f"--- {имя}")
        скажи(f"    задача {tid}; ответ: {ответ.replace(chr(10), ' ⏎ ')[:90]}")
        if и["status"] == "FOUND":
            скажи(f"    FOUND   {и['marker']} → {и['verdict']} ({и['reason']})")
        else:
            скажи(f"    ОТКАЗ   {и['status']}: {и['reason']}")
        скажи(f"    ждали {ждём_статус}{' ' + ждём_вид if ждём_вид else ''} → {'ВЕРНО' if ок else 'НЕВЕРНО'}")
    скажи("")
    скажи(f"ПРОБ: {sum(итоги)} из {len(итоги)} — {'ВСЕ ВЕРНЫ' if all(итоги) else 'ЕСТЬ ОШИБКИ'}")
    if улики:
        улики.mkdir(parents=True, exist_ok=True)
        (улики / "razbor-primerov.txt").write_text("\n".join(вывод) + "\n", encoding="utf-8")
    return 0 if all(итоги) else 1


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        print(__doc__); sys.exit(2)
    if a[0] == "--proby":
        у = Path(a[a.index("--uliki") + 1]).resolve() if "--uliki" in a else None
        sys.exit(пробы(у))
    if a[0] == "declare":
        print(declare(a[1], a[2] if len(a) > 2 else None)); sys.exit(0)
    if a[0] == "parse":
        sys.exit(show(parse(sys.stdin.read(), a[1])))
    print(__doc__); sys.exit(2)
