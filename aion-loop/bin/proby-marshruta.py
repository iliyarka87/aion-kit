#!/usr/bin/env python3
"""Пробы N-L0-04 — маршрутизатор контекста (L0.8, INV-ORIENT-003).

Три типовые задачи дают пакет ровно нужного состава. Всё остальное —
ROUTE_NOT_FOUND, и «всё остальное» проверяется нарочно широко: опечатка,
другой регистр, подстрока, пробел, пустота. Плюс карта без масок и без
путей наружу, и пропавший файл как ошибка, а не молча укороченный пакет.

Запуск:  python3 bin/proby-marshruta.py [--uliki папка]
С --uliki складывает вывод команд и размеры пакетов в папку — это и есть
обязательные улики пункта.
"""
from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parent.parent
AIONCTL = КОРЕНЬ / "bin" / "aionctl"
КАРТА = КОРЕНЬ / "routes.json"

ТИПОВЫЕ = ("orient", "item", "law")
ЧУЖИЕ = ("", "deploy", "itm", "Item", "ITEM", "ite", "items", " item", "item ",
         "orien", "law2", "orient/item", "../item", "*", "all")

итоги = []
улики = {"команды": [], "размеры": {}}


def проба(имя, условие, подробно=""):
    итоги.append((имя, bool(условие), подробно))
    print(f"  [{'ДА ' if условие else 'НЕТ'}] {имя}{('  — ' + подробно) if подробно and not условие else ''}")


def зов(*дов):
    р = subprocess.run([str(AIONCTL), *дов], capture_output=True, text=True, cwd=КОРЕНЬ)
    улики["команды"].append({"команда": "aionctl " + " ".join(repr(д) if " " in д or д == "" else д for д in дов),
                           "код": р.returncode, "вывод": (р.stdout + р.stderr).strip()[:1500]})
    return р.returncode, р.stdout.strip(), р.stderr.strip()


def модуль_aionctl():
    загрузчик = importlib.machinery.SourceFileLoader("aionctl", str(AIONCTL))
    спец = importlib.util.spec_from_loader("aionctl", загрузчик)
    м = importlib.util.module_from_spec(спец)
    загрузчик.exec_module(м)
    return м


def главное():
    print("ПРОБЫ N-L0-04 · маршрутизатор контекста")
    карта = json.loads(КАРТА.read_text(encoding="utf-8"))
    маршруты = карта["маршруты"]

    print("\n1. карта маршрутов честная")
    проба("ровно три типовые задачи", set(маршруты) == set(ТИПОВЫЕ), str(sorted(маршруты)))
    for имя, м in маршруты.items():
        файлы = м.get("файлы", [])
        проба(f"{имя}: маршрут не пуст", bool(файлы))
        проба(f"{имя}: без масок, папок и путей наружу",
              all(not any(з in ф for з in ("*", "?", "..")) and not ф.startswith("/")
                  and not ф.endswith("/") for ф in файлы), str(файлы))
        проба(f"{имя}: все файлы существуют", all((КОРЕНЬ / ф).is_file() for ф in файлы),
              str([ф for ф in файлы if not (КОРЕНЬ / ф).is_file()]))

    print("\n2. три типовые задачи дают пакет ровно нужного состава")
    for имя in ТИПОВЫЕ:
        код, вывод, _ = зов("context", имя)
        проба(f"{имя}: код 0", код == 0, f"код {код}")
        try:
            п = json.loads(вывод)
        except ValueError:
            проба(f"{имя}: вывод — json", False, вывод[:80]); continue
        ждём = маршруты[имя]["файлы"]
        дали = [ф["файл"] for ф in п["состав"]]
        проба(f"{имя}: состав = маршрут, без лишнего и без пропусков", дали == ждём,
              f"дали {дали}")
        проба(f"{имя}: у каждого файла размер > 0 и sha256",
              all(ф["байт"] > 0 and len(ф["sha256"]) == 64 for ф in п["состав"]))
        проба(f"{имя}: суммарный размер = сумма файлов",
              п["байт_всего"] == sum(ф["байт"] for ф in п["состав"]))
        # sha256 в пакете совпадает с файлом на диске — пакет не подменён
        проба(f"{имя}: отпечатки совпадают с диском",
              all(hashlib.sha256((КОРЕНЬ / ф["файл"]).read_bytes()).hexdigest() == ф["sha256"]
                  for ф in п["состав"]))
        улики["размеры"][имя] = {"файлов": п["файлов"], "байт_всего": п["байт_всего"],
                               "состав": {ф["файл"]: ф["байт"] for ф in п["состав"]}}

    print("\n3. неизвестная задача — ROUTE_NOT_FOUND, не догадка")
    for чужая in ЧУЖИЕ:
        код, вывод, ошибка = зов("context", чужая)
        проба(f"{chr(171)}{чужая}{chr(187)}: ровно ROUTE_NOT_FOUND и код 2",
              код == 2 and вывод == "ROUTE_NOT_FOUND" and not ошибка,
              f"код {код}, вывод {вывод[:60]!r}")

    print("\n4. пропавший файл — ошибка маршрута, не молчаливое укорочение")
    a = модуль_aionctl()
    with tempfile.TemporaryDirectory() as врем:
        к = Path(врем)
        (к / "есть.md").write_text("x", encoding="utf-8")
        сломанная = {"маршруты": {"t": {"файлы": ["есть.md", "нет.md"]}}}
        п, беда = a.пакет(к, "t", сломанная)
        проба("пакет не собран", п is None)
        проба("названо, чего не хватает", "нет.md" in беда, беда)
        проба("это не ROUTE_NOT_FOUND — беда другая", беда != a.ROUTE_NOT_FOUND)
        маска = {"маршруты": {"t": {"файлы": ["*.md"]}}}
        п, беда = a.пакет(к, "t", маска)
        проба("маска в маршруте отвергнута", п is None and "маск" in беда, беда)
        наружу = {"маршруты": {"t": {"файлы": ["../есть.md"]}}}
        п, беда = a.пакет(к, "t", наружу)
        проба("путь наружу отвергнут", п is None, беда)
        пустой = {"маршруты": {"t": {"файлы": []}}}
        п, беда = a.пакет(к, "t", пустой)
        проба("пустой маршрут — ошибка карты, не пустой пакет", п is None and "пуст" in беда, беда)

    print("\n5. инварианты, включённые всегда")
    код, вывод, _ = зов("routes")
    проба("aionctl routes перечисляет ровно три", код == 0 and вывод.count("\n") == 2)
    код, _, _ = зов("bootstrap")
    проба("прежние команды не сломаны: bootstrap", код == 0, f"код {код}")

    всего = len(итоги); прошло = sum(1 for _, ок, _ in итоги if ок)
    print(f"\nИТОГ: {прошло} из {всего}")
    return прошло == всего


if __name__ == "__main__":
    ок = главное()
    if "--uliki" in sys.argv:
        папка = Path(sys.argv[sys.argv.index("--uliki") + 1])
        папка.mkdir(parents=True, exist_ok=True)
        (папка / "vyvod-komand.json").write_text(
            json.dumps(улики["команды"], ensure_ascii=False, indent=2), encoding="utf-8")
        (папка / "razmery-paketov.json").write_text(
            json.dumps(улики["размеры"], ensure_ascii=False, indent=2), encoding="utf-8")
        (папка / "itog-prob.txt").write_text(
            "\n".join(f"{'ДА ' if ок_ else 'НЕТ'} {имя}" for имя, ок_, _ in итоги)
            + f"\nИТОГ: {sum(1 for _, о, _ in итоги if о)} из {len(итоги)}\n", encoding="utf-8")
        print(f"улики: {папка}")
    sys.exit(0 if ок else 1)
