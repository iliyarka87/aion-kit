#!/usr/bin/env python3
"""Очередь решений владельца (§20 Мастера, N-L0-12).

Вопрос владельцу — это запись в registries/owner-decision-queue.jsonl, и только она.
Никакого окна-разрешения, никакого ожидания у клавиатуры: агент записывает вопрос,
рекомендацию, безопасное действие по умолчанию и что можно делать дальше — и идёт
делать это дальше. Владелец отвечает, когда придёт: `answer`.

Поля §20: DECISION_ID, TASK_ID, CATEGORY, QUESTION, WHY_REQUIRED, OPTIONS,
RECOMMENDED_OPTION, RISK, DEFAULT_SAFE_ACTION, WHAT_CAN_CONTINUE, BLOCKED_DEPENDENCIES.
Служебные: STATUS (PENDING / ANSWERED / WITHDRAWN), ASKED_AT, ANSWERED_AT, ANSWER.

    python3 bin/ochered.py add --task N-… --category … --question … --why … \\
        --options "а|б|в" --recommended а --risk GREEN --default … --continue … [--blocked N-…,N-…]
    python3 bin/ochered.py list                     ожидающие и отвеченные
    python3 bin/ochered.py answer <DECISION_ID> "<ответ>" --by owner
    python3 bin/ochered.py check                    доказательство: ожидание не останавливает
                                                     независимую работу (по доске чек-листа)
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parent.parent
ОЧЕРЕДЬ = КОРЕНЬ / "registries" / "owner-decision-queue.jsonl"
ПОЛЯ_20 = ["DECISION_ID", "TASK_ID", "CATEGORY", "QUESTION", "WHY_REQUIRED", "OPTIONS", "RECOMMENDED_OPTION",
           "RISK", "DEFAULT_SAFE_ACTION", "WHAT_CAN_CONTINUE", "BLOCKED_DEPENDENCIES"]
КАТЕГОРИИ = ("irreversible destructive action", "permanent data deletion", "irreversible migration",
             "major security boundary change", "financial commitment", "legal commitment",
             "public publishing commitment", "major architecture replacement",
             "Master/Constitution change", "Guardian security boundary change", "other")


def сейчас():
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def читать():
    if not ОЧЕРЕДЬ.exists():
        return []
    return [json.loads(с) for с in ОЧЕРЕДЬ.read_text(encoding="utf-8").splitlines() if с.strip()]


def писать(записи):
    ОЧЕРЕДЬ.parent.mkdir(parents=True, exist_ok=True)
    ОЧЕРЕДЬ.write_text("".join(json.dumps(з, ensure_ascii=False) + "\n" for з in записи), encoding="utf-8")


def add(a):
    записи = читать()
    n = len(записи) + 1
    з = {"DECISION_ID": f"OD-{n:03d}", "TASK_ID": a.task, "CATEGORY": a.category, "QUESTION": a.question,
         "WHY_REQUIRED": a.why, "OPTIONS": [o.strip() for o in a.options.split("|")],
         "RECOMMENDED_OPTION": a.recommended, "RISK": a.risk, "DEFAULT_SAFE_ACTION": a.default,
         "WHAT_CAN_CONTINUE": a.cont, "BLOCKED_DEPENDENCIES": [x for x in (a.blocked or "").split(",") if x],
         "STATUS": "PENDING", "ASKED_AT": сейчас(), "ANSWERED_AT": None, "ANSWER": None}
    if з["CATEGORY"] not in КАТЕГОРИИ:
        print(f"STOP: категория не из §20: {з['CATEGORY']}")
        return 2
    записи.append(з)
    писать(записи)
    print(f"записано {з['DECISION_ID']} — окно не открывалось, работа продолжается: {з['WHAT_CAN_CONTINUE']}")
    print(f"пока владелец молчит, действует по умолчанию: {з['DEFAULT_SAFE_ACTION']}")
    return 0


def answer(a):
    if a.by != "owner":
        print("STOP: отвечает только владелец (--by owner)")
        return 2
    записи = читать()
    for з in записи:
        if з["DECISION_ID"] == a.id:
            з["STATUS"], з["ANSWER"], з["ANSWERED_AT"] = "ANSWERED", a.answer, сейчас()
            писать(записи)
            print(f"{a.id}: ANSWERED — {a.answer}")
            return 0
    print(f"STOP: нет {a.id}")
    return 2


def list_(a):
    записи = читать()
    ждут = [з for з in записи if з["STATUS"] == "PENDING"]
    print(f"=== ОЧЕРЕДЬ РЕШЕНИЙ ВЛАДЕЛЬЦА: ожидают {len(ждут)}, отвечено {sum(1 for з in записи if з['STATUS']=='ANSWERED')} ===")
    for з in записи:
        print(f"  [{з['STATUS']:8s}] {з['DECISION_ID']} ({з['CATEGORY']}, риск {з['RISK']}) {з['QUESTION']}")
        print(f"             рекомендую: {з['RECOMMENDED_OPTION']}  · по умолчанию: {з['DEFAULT_SAFE_ACTION']}")
        if з["STATUS"] == "ANSWERED":
            print(f"             ответ владельца {з['ANSWERED_AT']}: {з['ANSWER']}")
    return 0


def check(a):
    """Ожидание решения не останавливает независимую работу: считаем по доске."""
    записи = читать()
    ждут = [з for з in записи if з["STATUS"] == "PENDING"]
    заперто = set()
    for з in ждут:
        заперто |= set(з["BLOCKED_DEPENDENCIES"])
    с = json.loads((КОРЕНЬ / "checklist" / "sostoyanie.json").read_text(encoding="utf-8"))["пункты"]
    готовые = [и for и, п in с.items() if п["state"] in ("READY", "ACTIVE")]
    можно = [и for и in готовые if и not in заперто]
    print(f"ожидают владельца: {len(ждут)}; заперто ими пунктов: {len(заперто)} {sorted(заперто) if заперто else ''}")
    print(f"на доске готовых/в работе: {len(готовые)}; из них можно продолжать без владельца: {len(можно)} → {', '.join(можно)}")
    print("окно-разрешение: не открывается — вопрос только записан; эта проверка идёт "
          + ("без терминала (stdin закрыт) и дошла до конца, ни у кого ничего не спросив" if not sys.stdin.isatty()
             else "в терминале; для доказательства запускать с < /dev/null"))
    print("ИТОГ: " + ("независимая работа продолжается" if можно else "ВСЁ ЗАПЕРТО — нужен владелец"))
    return 0 if можно else 1


def главное(argv):
    p = argparse.ArgumentParser(add_help=False)
    sub = p.add_subparsers(dest="cmd")
    a = sub.add_parser("add")
    for имя in ("task", "category", "question", "why", "options", "recommended", "risk", "default"):
        a.add_argument("--" + имя, required=True)
    a.add_argument("--continue", dest="cont", required=True)
    a.add_argument("--blocked")
    ans = sub.add_parser("answer"); ans.add_argument("id"); ans.add_argument("answer"); ans.add_argument("--by", default="")
    sub.add_parser("list"); sub.add_parser("check")
    args = p.parse_args(argv)
    if not args.cmd:
        print(__doc__)
        return 2
    return {"add": add, "answer": answer, "list": list_, "check": check}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(главное(sys.argv[1:]))
