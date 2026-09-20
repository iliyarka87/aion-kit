#!/usr/bin/env python3
"""Пробы защиты от двойного исполнения (N-L1-05).

Ключ доставки = номер задачи : попытка (item:attempt). Провод (svyaz/src/link.py)
доставляет один ключ один раз; повтор того же ключа записывается в журнал доставок
и НЕ отправляется — исполнитель не начинает ту же работу второй раз. Повтор после
сбоя — это новая попытка от ворот, новый ключ, новая доставка.

    1. обычная доставка            → доставлено, почтальон вызван 1 раз
    2. повторная доставка того же  → не отправлено (DUPLICATE), почтальон по-прежнему 1 раз
    3. повтор после сбоя (новая попытка) → доставлено, почтальон 2 раза
    4. результат привязан к номеру и попытке — по реестру задач (ворота)

Почтальон подменён заглушкой-счётчиком: в окно ничего не летит, считаются вызовы.

    python3 bin/proby-dostavki.py [--uliki <dir>]
"""
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("link", КОРЕНЬ / "svyaz" / "src" / "link.py")
link = importlib.util.module_from_spec(spec)
spec.loader.exec_module(link)

вывод = []


def скажи(т=""):
    вывод.append(т); print(т)


def главное():
    улики = Path(sys.argv[sys.argv.index("--uliki") + 1]).resolve() if "--uliki" in sys.argv else None
    вызовы = []
    link.mailbox.послать = lambda session, text: (вызовы.append((session, text[:40])) or True)
    link.target_window = lambda: "stub-window-0001"
    link.mark = lambda session: 0
    журнал = Path(tempfile.mkdtemp(prefix="proba-dostavki-")) / "dostavki.jsonl"
    итоги = {}

    d1 = link.send("TASK N-PROBA attempt A-000000000001", key="N-PROBA:A-000000000001", ledger=журнал)
    скажи(f"--- проба 1: обычная доставка → {d1[0]}, {d1[2]}; вызовов почтальона: {len(вызовы)}")
    итоги["1. обычная доставка"] = d1[0] and len(вызовы) == 1

    d2 = link.send("TASK N-PROBA attempt A-000000000001", key="N-PROBA:A-000000000001", ledger=журнал)
    скажи(f"--- проба 2: повторная доставка того же ключа → доставлено={d2[0]}; {d2[2][:70]}; вызовов почтальона: {len(вызовы)}")
    итоги["2. повтор того же номера и попытки → второго запуска нет"] = (not d2[0]) and d2[2].startswith("DUPLICATE") and len(вызовы) == 1

    d3 = link.send("TASK N-PROBA attempt A-000000000002", key="N-PROBA:A-000000000002", ledger=журнал)
    скажи(f"--- проба 3: повтор после сбоя (новая попытка от ворот) → {d3[0]}; вызовов почтальона: {len(вызовы)}")
    итоги["3. новая попытка после сбоя → доставлено заново"] = d3[0] and len(вызовы) == 2

    скажи("--- журнал провода (доставки), песочница:")
    записи = [json.loads(l) for l in журнал.read_text(encoding="utf-8").splitlines() if l.strip()]
    for з in записи:
        скажи("    " + json.dumps(з, ensure_ascii=False)[:150])
    статусы = [з["status"] for з in записи]
    итоги["журнал: delivered, duplicate_suppressed, delivered"] = статусы == ["delivered", "duplicate_suppressed", "delivered"]

    # 4. результат привязан к номеру и попытке — реестр задач ворот
    # синтетический реестр задач той же формы, что checklist/sostoyanie.json: две попытки одного пункта
    пример = "N-EXAMPLE-01"
    с = {пример: {"state": "PASS_CANDIDATE", "attempts": [{"attempt_id": "A-0001", "result": "FAIL"}, {"attempt_id": "A-0002", "result": "PASS_CANDIDATE"}]}}
    попытки = [(a["attempt_id"], a["result"]) for a in с[пример]["attempts"]]
    скажи(f"--- проба 4: реестр задач: {пример} → попытки и результаты {попытки}")
    итоги["4. результат привязан к номеру и попытке"] = len(попытки) >= 2 and all(a and r for a, r in попытки)

    скажи("=== ИТОГ ПРОБ ===")
    for имя, ок in итоги.items():
        скажи(f"  {'✓' if ок else '✗'} {имя}")
    всё = all(итоги.values())
    скажи(f"ПРОБ: {sum(итоги.values())} из {len(итоги)} — {'ВСЕ ВЕРНЫ' if всё else 'ЕСТЬ ОШИБКИ'}")
    if улики:
        улики.mkdir(parents=True, exist_ok=True)
        (улики / "vyvod-prob.txt").write_text("\n".join(вывод) + "\n", encoding="utf-8")
        (улики / "dostavki-pesochnica.jsonl").write_text(журнал.read_text(encoding="utf-8"), encoding="utf-8")
    return 0 if всё else 1


if __name__ == "__main__":
    sys.exit(главное())
