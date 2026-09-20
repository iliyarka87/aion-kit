#!/usr/bin/env python3
"""Проверка по реестру отказов: спросить ДО действия, не после.

Поток §5 / 04-legacy: REQUESTED ACTION → FAILURE REGISTRY CHECK → KNOWN-BAD MATCH?
    совпало     → BLOCKED, имя отказа и безопасная замена, код 3
    не совпало  → PASS, код 0
Сигнатуры лежат в registries/failures.jsonl, поле KNOWN_BAD_ACTIONS (регулярные
выражения, регистр не важен). Проверка ничего не пишет и ничего не решает
сама — она только называет.

    python3 bin/proverka-otkazov.py "текст предлагаемого действия"
    python3 bin/proverka-otkazov.py --proby        воспроизвести оба сценария
"""
import json
import re
import sys
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parent.parent
РЕЕСТР = КОРЕНЬ / "registries" / "failures.jsonl"


def записи():
    for строка in РЕЕСТР.read_text(encoding="utf-8").splitlines():
        if строка.strip():
            yield json.loads(строка)


def проверить(действие: str) -> dict:
    for з in записи():
        for сиг in з.get("KNOWN_BAD_ACTIONS") or []:
            if re.search(сиг, действие, flags=re.IGNORECASE):
                return {"verdict": "BLOCKED", "failure": з["FAILURE_ID"],
                        "signature": сиг, "safe_alternative": з["SAFE_ALTERNATIVE"],
                        "action": действие}
    return {"verdict": "PASS", "action": действие}


def показать(итог: dict) -> int:
    if итог["verdict"] == "BLOCKED":
        print(f"BLOCKED  {итог['failure']}")
        print(f"  сигнатура:  {итог['signature']}")
        print(f"  безопасно:  {итог['safe_alternative']}")
        return 3
    print("PASS     неизвестная сигнатура — реестр не возражает")
    return 0


ПРОБЫ = [
    ("поставлю прямо на его телефон через devicectl install", "BLOCKED", "STABLE_MUTATION"),
    ("процесс есть, значит работает — служба здорова", "BLOCKED", "HEALTH_FALSE_POSITIVE"),
    ("заодно поправлю ещё два файла рядом", "BLOCKED", "TASK_SCOPE_EXPANSION"),
    ("прочитать state/current.json и доложить доску", "PASS", None),
    ("собрать улики в evidence/N-L0-06 и сдать воротами", "PASS", None),
]


def пробы() -> int:
    всё = True
    n = sum(1 for _ in записи())
    сигнатур = sum(len(з.get("KNOWN_BAD_ACTIONS") or []) for з in записи())
    print(f"реестр: {n} записей, {сигнатур} сигнатур")
    for действие, ждём, имя in ПРОБЫ:
        итог = проверить(действие)
        ок = итог["verdict"] == ждём and (имя is None or итог.get("failure") == имя)
        всё &= ок
        print(f"--- «{действие}»")
        показать(итог)
        print(f"ждали {ждём}{' ' + имя if имя else ''} → {'ВЕРНО' if ок else 'НЕВЕРНО'}")
    print(f"ПРОБ: {sum(1 for д, ж, и in ПРОБЫ if проверить(д)['verdict'] == ж)} из {len(ПРОБЫ)} — "
          f"{'ВСЕ ВЕРНЫ' if всё else 'ЕСТЬ ОШИБКИ'}")
    return 0 if всё else 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    if sys.argv[1] == "--proby":
        sys.exit(пробы())
    sys.exit(показать(проверить(" ".join(sys.argv[1:]))))
