#!/usr/bin/env python3
"""Судья пункта чек-листа: три независимых чтения, зачёт по двум из трёх.

Беда, ради которой это написано: один и тот же судья на одних и тех же уликах
давал то зачёт, то отказ. Это не спор, это разброс, и лечится он не лучшим
вопросом, а несколькими независимыми чтениями и писаным правилом сведения.

Правило простое и названо вслух:

    три чтения одного и того же, каждое в своей отдельной беседе;
    зачёт, если зачёт сказали хотя бы двое из трёх.

Каждое чтение идёт в новой пустой нити Codex: судья, помнящий свой прошлый
вердикт, — это один голос, поданный трижды.

Он ничего не записывает в состояние. Его дело — сказать, а зачёт ставят
ворота, и только они.

Запуск:
    ~/.aion-sudya/venv/bin/python sudit.py N-L0-04 --uliki out.txt razmery.txt
    ~/.aion-sudya/venv/bin/python sudit.py N-L0-04 --tekst "что сделано и чем доказано"
"""

from __future__ import annotations

import argparse
import os
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import codex_provider  # noqa: F401  регистрирует нашего Codex под именем codex

from inspect_ai import Epochs, Task, eval as inspect_eval, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import (
    CORRECT,
    INCORRECT,
    Score,
    Target,
    accuracy,
    at_least,
    scorer,
)
from inspect_ai.solver import TaskState, generate

OPREDELENIE = Path(os.environ.get("AION_ROOT", ".")) / "checklist" / "opredelenie.json"
CHTENIY = 3          # сколько независимых чтений
NUZHNO = 2           # сколько из них должны сказать «зачёт»

MERILO = """Ты судья. Перед тобой один пункт работы и улики к нему.

ТВОЯ ЗАДАЧА — решить одно: улики доказывают выполнение условия зачёта или нет.

Суди строго по условию, написанному ниже. Не по тому, хорошо ли сделано,
не по тому, красив ли код, и не по тому, что ты сделал бы иначе.

ОТКАЗ, если верно хотя бы одно:
  · улик, названных обязательными, нет или они не показаны;
  · улики показывают не то, о чём говорит условие;
  · вместо вывода команд — пересказ словами «сделано», «работает», «проверено»;
  · условие требует нескольких случаев, а показан один.

ЗАЧЁТ, если условие покрыто уликами целиком. Неполнота — это отказ,
а не «почти зачёт».

ОТВЕТ РОВНО В ДВЕ СТРОКИ, без вступления:
PASS или FAIL
одна строка: чем именно это доказано, или чего именно не хватает
"""


def pyunkt(nomer: str) -> dict:
    with OPREDELENIE.open(encoding="utf-8") as handle:
        opredelenie = json.load(handle)
    punkty = opredelenie["пункты"]
    if nomer not in punkty:
        raise SystemExit("нет такого пункта: %s" % nomer)
    return punkty[nomer]


def vopros(p: dict, uliki: str) -> str:
    return "\n".join([
        MERILO,
        "ПУНКТ: %s — %s" % (p["id"], p.get("имя", "")),
        "ЦЕЛЬ: %s" % p.get("objective", "—"),
        "УСЛОВИЕ ЗАЧЁТА: %s" % p.get("acceptance", "—"),
        "ОБЯЗАТЕЛЬНЫЕ УЛИКИ: %s" % p.get("required_evidence", "—"),
        "",
        "УЛИКИ, ПРЕДЪЯВЛЕННЫЕ ИСПОЛНИТЕЛЕМ:",
        uliki.strip() or "(улик не предъявлено)",
    ])


@scorer(metrics=[accuracy()])
def verdikt():
    """Превращает слово судьи в голос. Ничего не проверяет сам."""
    async def score(state: TaskState, target: Target) -> Score:
        otvet = (state.output.completion or "").strip()
        pervoe = re.split(r"[\s:.,]+", otvet.upper().lstrip("*# "), 1)
        slovo = pervoe[0] if pervoe else ""
        prichina = "\n".join(otvet.splitlines()[1:]).strip()[:400]
        if slovo == "PASS":
            return Score(value=CORRECT, answer="PASS", explanation=prichina)
        if slovo == "FAIL":
            return Score(value=INCORRECT, answer="FAIL", explanation=prichina)
        # Судья, не сказавший ни того ни другого, считается сказавшим «отказ»:
        # молчание не зачёт. Но это видно в ответе, а не проглатывается.
        return Score(value=INCORRECT, answer="НЕ ПОНЯЛ",
                     explanation="судья ответил не по форме: %s" % otvet[:200])
    return score


def sudit(nomer: str, uliki: str) -> dict:
    p = pyunkt(nomer)

    @task
    def delo() -> Task:
        return Task(
            dataset=[Sample(input=vopros(p, uliki), target="PASS")],
            solver=generate(),
            scorer=verdikt(),
            epochs=Epochs(CHTENIY, at_least(NUZHNO)),
        )

    logs = inspect_eval(delo(), model="codex/local",
                        log_dir="/tmp/aion-sudya-log", display="none")
    log = logs[0]
    if log.status != "success":
        return {"пункт": nomer, "вердикт": "НЕ СОСТОЯЛСЯ",
                "почему": str(getattr(log, "error", "") or log.status)[:300]}

    golosa, prichiny = [], []
    for s in (log.samples or []):
        sc = (s.scores or {}).get("verdikt")
        golosa.append(getattr(sc, "answer", "?") if sc else "?")
        if sc is not None and getattr(sc, "explanation", ""):
            prichiny.append(sc.explanation)

    za = sum(1 for g in golosa if g == "PASS")
    itog = "PASS" if za >= NUZHNO else "FAIL"
    return {
        "пункт": nomer,
        "имя": p.get("имя"),
        "вердикт": itog,
        "голоса": golosa,
        "за_зачёт": za,
        "нужно": NUZHNO,
        "из": CHTENIY,
        "единогласно": len(set(golosa)) == 1,
        "причины": prichiny,
        "условие": p.get("acceptance"),
        "примечание": "судья только говорит; зачёт пишут ворота",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="судья пункта: трижды и по двум из трёх")
    parser.add_argument("punkt", help="например N-L0-04")
    parser.add_argument("--uliki", nargs="*", default=[], help="файлы с уликами")
    parser.add_argument("--tekst", default="", help="улики прямо строкой")
    args = parser.parse_args()

    куски = [args.tekst] if args.tekst else []
    for put in args.uliki:
        p = Path(put)
        куски.append("--- %s ---\n%s" % (p.name, p.read_text(encoding="utf-8", errors="replace")))

    итог = sudit(args.punkt, "\n\n".join(куски))
    print(json.dumps(итог, ensure_ascii=False, indent=2))
    return 0 if итог.get("вердикт") == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
