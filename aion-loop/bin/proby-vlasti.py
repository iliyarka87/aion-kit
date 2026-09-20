#!/usr/bin/env python3
"""Пробы оси власти (N-L0-07): конфликт решается уровнем, отсутствие уровня — предупреждение.

Живой канон не трогается — работа в песочной копии (см. proby-sverki.py).

    1. конфликт 05 ≠ 01 по версии Мастера при уровнях 01=100, 05=80
       → reconcile называет победителем 01 и велит поправить 05
    2. тот же конфликт, но уровни перевёрнуты (05=100, 01=80), порядок чтения прежний
       → победитель 05: значит решает уровень, а не порядок чтения
    3. у 03-HANDOFF.md убрана строка AUTHORITY_LEVEL
       → [WARN] «без AUTHORITY_LEVEL», публикация не закрыта из-за этого
    4. чистая копия → предупреждений ноль, код 0

    python3 bin/proby-vlasti.py [--uliki <dir>]
"""
import importlib.util
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("sverki", КОРЕНЬ / "bin" / "proby-sverki.py")
sverki = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sverki)

вывод = []


def скажи(т=""):
    вывод.append(т)
    print(т, flush=True)


def версия_в_05_сломать(к):
    п = к / "05-CURRENT-STATE.md"
    т = re.sub(r"(MASTER_VERSION\s*=\s*)MASTER-", r"\1MASTER-PROBA-", п.read_text(encoding="utf-8"), count=1)
    п.write_text(т, encoding="utf-8")


def уровни(к, **новые):
    п = к / "authority.json"
    a = json.loads(п.read_text(encoding="utf-8"))
    for имя, ур in новые.items():
        a["документы"][имя]["уровень"] = ур
        д = к / имя
        д.write_text(re.sub(r"^(\s*AUTHORITY_LEVEL\s*=\s*)\d+", rf"\g<1>{ур}", d, count=1, flags=re.M)
                     if (d := д.read_text(encoding="utf-8")) else d, encoding="utf-8")
    п.write_text(json.dumps(a, ensure_ascii=False, indent=2), encoding="utf-8")


def коммит(к):
    sverki.зов("git", "-c", "user.name=p", "-c", "user.email=p@l", "commit", "-qam", "proba", cwd=к)


def проба(имя, к, ждём_код, зацепки):
    код, в = sverki.сверка(к)
    ок = код == ждём_код and all(z in в for z in зацепки)
    скажи(f"--- проба «{имя}» ---"); скажи(в)
    скажи(f"код выхода: {код} (ждали {ждём_код}); зацепки {zацепки_текст(зацепки)} → {'ВЕРНО' if ок else 'НЕВЕРНО'}")
    скажи()
    return ок


def zацепки_текст(z):
    return " + ".join(f"«{x}»" for x in z)


def главное():
    улики = Path(sys.argv[sys.argv.index("--uliki") + 1]).resolve() if "--uliki" in sys.argv else None
    база = Path(tempfile.mkdtemp(prefix="proba-vlasti-"))
    итоги = {}
    try:
        к = база / "konflikt"; sverki.копия(к)
        версия_в_05_сломать(к); коммит(к)
        итоги["конфликт: побеждает 01 (100 > 80)"] = проба(
            "конфликт версии 05 ≠ 01, уровни 01=100, 05=80", к, 1,
            ["побеждает 01-AION-MASTER.md (уровень 100 > 80)", "поправить 05-CURRENT-STATE.md"])

        к = база / "perevorot"; sverki.копия(к)
        версия_в_05_сломать(к)
        уровни(к, **{"05-CURRENT-STATE.md": 100, "01-AION-MASTER.md": 80}); коммит(к)
        итоги["перевёрнутые уровни: побеждает 05 — решает уровень, не порядок чтения"] = проба(
            "тот же конфликт, уровни перевёрнуты 05=100, 01=80", к, 1,
            ["побеждает 05-CURRENT-STATE.md (уровень 100 > 80)", "поправить 01-AION-MASTER.md"])

        к = база / "bez-urovnya"; sverki.копия(к)
        д = к / "03-HANDOFF.md"
        д.write_text(re.sub(r"^\s*AUTHORITY_LEVEL\s*=.*\n", "", д.read_text(encoding="utf-8"), count=1, flags=re.M),
                     encoding="utf-8")
        коммит(к)
        итоги["без уровня: предупреждение, публикация не закрыта"] = проба(
            "03-HANDOFF.md без AUTHORITY_LEVEL", к, 0,
            ["[WARN   ] документы: 03-HANDOFF.md: без AUTHORITY_LEVEL", "ПРЕДУПРЕЖДЕНИЙ: 1", "публикация разрешена"])

        к = база / "chistaya"; sverki.копия(к)
        итоги["чистая: 12 уровней сошлись, код 0"] = проба(
            "чистая копия", к, 0, ["ось власти — 12 документов", "публикация разрешена"])
    finally:
        shutil.rmtree(база, ignore_errors=True)

    скажи("=== ИТОГ ПРОБ ===")
    for имя, ок in итоги.items():
        скажи(f"  {'✓' if ок else '✗'} {имя}")
    всё = all(итоги.values())
    скажи(f"ПРОБ: {sum(итоги.values())} из {len(итоги)} — {'ВСЕ ВЕРНЫ' if всё else 'ЕСТЬ ОШИБКИ'}")
    if улики:
        улики.mkdir(parents=True, exist_ok=True)
        (улики / "vyvod-reconcile.txt").write_text("\n".join(вывод) + "\n", encoding="utf-8")
        скажи(f"улики: {улики}")
    return 0 if всё else 1


if __name__ == "__main__":
    sys.exit(главное())
