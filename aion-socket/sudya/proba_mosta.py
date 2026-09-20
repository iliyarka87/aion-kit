#!/usr/bin/env python3
"""Проба моста: правда ли Inspect умеет править нашим Codex и сводить голоса.

Ничего не судит по делу. Задаёт трижды один пустяковый вопрос и требует,
чтобы зачёт вышел по правилу «хотя бы двое из трёх» — то самое сведение,
ради которого Inspect и берётся.

Запуск:  ~/.aion-sudya/venv/bin/python proba_mosta.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import codex_provider  # noqa: F401  регистрирует провайдера под именем codex

from inspect_ai import Epochs, Task, eval as inspect_eval, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import at_least, includes
from inspect_ai.solver import generate


@task
def proba() -> Task:
    return Task(
        dataset=[Sample(input="Skolko budet 7 umnozhit na 6? "
                              "Otvet tolko chislom, bez slov.",
                        target="42")],
        solver=generate(),
        scorer=includes(),
        # Три независимых чтения и правило их сведения. Это и есть лекарство
        # от судьи, который на одних уликах даёт то зачёт, то отказ.
        epochs=Epochs(3, at_least(2)),
    )


def main() -> int:
    logs = inspect_eval(proba(), model="codex/local", log_dir="/tmp/aion-sudya-log",
                        display="plain")
    log = logs[0]
    print()
    print("  состояние прогона :", log.status)
    if log.results and log.results.scores:
        for score in log.results.scores:
            for name, metric in (score.metrics or {}).items():
                print(f"  {score.name} / {name}: {metric.value}")
    print("  образцов          :", len(log.samples or []))
    if log.samples:
        otvety = [s.output.completion.strip()[-20:] for s in log.samples]
        print("  что ответил Codex :", otvety)
    horosho = log.status == "success"
    print()
    print("  СВЕДЕНИЕ ТРЁХ ГОЛОСОВ ЧЕРЕЗ НАШ CODEX:", "вышло" if horosho else "НЕ ВЫШЛО")
    return 0 if horosho else 1


if __name__ == "__main__":
    sys.exit(main())
