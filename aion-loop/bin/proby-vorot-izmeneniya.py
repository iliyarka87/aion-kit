#!/usr/bin/env python3
"""Пробы ворот изменения (N-L2-01): семь условий по отдельности → BLOCKED; чисто → ALLOW;
неизвестное/неполное состояние → BLOCKED, никогда не ALLOW.

Каждый сценарий — своя песочная копия канона (живое не трогается), в которой нарушено
ровно одно условие, остальные чисты. Вывод `aionctl gate` каждого сценария ложится
отдельным файлом в папку улик.

    python3 bin/proby-vorot-izmeneniya.py [--uliki <dir>]
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

ДЕЙСТВИЕ = "прочитать доску и доложить"


def gate(к, действие):
    return sverki.зов(sys.executable, str(к / "bin" / "aionctl"), "gate", действие, cwd=к, env={"AION_HOME": str(к)})


def пересобрать_зеркало(к):
    sverki.зов(sys.executable, str(к / "state" / "sostoyanie.py"), "--sobrat", cwd=к)


def правка_05(к, ключ, значение):
    п = к / "05-CURRENT-STATE.md"
    т = п.read_text(encoding="utf-8")
    т = re.sub(rf"^(\s*{ключ}\s*=\s*).*$", rf"\g<1>{значение}", т, count=1, flags=re.M)
    п.write_text(т, encoding="utf-8")


def главное():
    улики = Path(sys.argv[sys.argv.index("--uliki") + 1]).resolve() if "--uliki" in sys.argv else None
    if улики:
        улики.mkdir(parents=True, exist_ok=True)
    база = Path(tempfile.mkdtemp(prefix="proba-vorot-"))
    итоги = {}
    сценарии = []

    def сценарий(имя_файла, имя, действие, подготовка, ждём_код, ждём_условие=None):
        к = база / имя_файла
        sverki.копия(к)
        подготовка(к)
        код, в = gate(к, действие)
        сработали = [с[9:].split("  —")[0].strip() for с in в.splitlines() if s_block(с)]
        if ждём_код == 3 and ждём_условие:
            ок = код == 3 and сработали == [ждём_условие]
            ждали = f"BLOCKED ровно по «{ждём_условие}»"
        elif ждём_код == 3:
            ок = код == 3 and bool(сработали)
            ждали = "BLOCKED (не ALLOW)"
        else:
            ок = код == 0 and not сработали
            ждали = "ALLOW"
        итоги[имя] = ок
        текст = f"# {имя}\n# действие: {действие}\n# ждали: {ждали}; получили: код {код}, сработали {сработали} → {'ВЕРНО' if ок else 'НЕВЕРНО'}\n\n{в}\n"
        сценарии.append((имя_файла, текст))
        print(f"--- {имя}: код {код}, сработали {сработали} → {'ВЕРНО' if ок else 'НЕВЕРНО'}")
        if улики:
            (улики / f"{имя_файла}.txt").write_text(текст, encoding="utf-8")

    def s_block(с):
        return с.strip().startswith("[BLOCK]")

    сценарий("01-boot", "1. boot != PASS (нет 00-START-HERE.md)", ДЕЙСТВИЕ,
             lambda к: (к / "00-START-HERE.md").unlink(), 3, "boot != PASS")
    def st_invalid(к):
        p = к / "state" / "current.json"; d = json.loads(p.read_text(encoding="utf-8")); d["state_status"] = "DRAFT"
        p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    сценарий("02-state-invalid", "2. state invalid (state_status = DRAFT, зеркало ≠ 05)", ДЕЙСТВИЕ, st_invalid, 3, "state invalid")
    def doc_conflict(к):
        п = к / "05-CURRENT-STATE.md"
        п.write_text(re.sub(r"(MASTER_VERSION\s*=\s*)MASTER-", r"\1MASTER-PROBA-", п.read_text(encoding="utf-8"), count=1), encoding="utf-8")
        пересобрать_зеркало(к)
    сценарий("03-document-conflict", "3. DOCUMENT_CONFLICT (05 ≠ 01 по версии Мастера)", ДЕЙСТВИЕ, doc_conflict, 3, "DOCUMENT_CONFLICT")
    сценарий("04-stable-protected", "4. Stable protected (действие трогает zolotaya-kopiya)", "поправить zolotaya-kopiya/petlya-2.1/stend", lambda к: None, 3, "Stable protected")
    def change_unknown(к):
        правка_05(к, "CURRENT_CHANGE", "UNKNOWN"); пересобрать_зеркало(к)
    сценарий("05-change-unknown", "5. Change unknown (CURRENT_CHANGE = UNKNOWN)", ДЕЙСТВИЕ, change_unknown, 3, "Change unknown")
    def task_unknown(к):
        правка_05(к, "CURRENT_TASK", "UNKNOWN"); пересобрать_зеркало(к)
    сценарий("06-unknown-critical", "6. UNKNOWN по критической проверке (CURRENT_TASK = UNKNOWN)", ДЕЙСТВИЕ, task_unknown, 3, "UNKNOWN по критической проверке")
    сценарий("07-failure-signature", "7. сигнатура провала (devicectl install на телефон)", "поставлю прямо на его телефон через devicectl install", lambda к: None, 3, "сигнатура провала")
    сценарий("08-clean-allow", "8. чистое подтверждённое состояние → ALLOW", ДЕЙСТВИЕ, lambda к: None, 0)
    def broken_state(к):
        (к / "state" / "current.json").write_text("{ это не json", encoding="utf-8")
    сценарий("09-unknown-incomplete", "9. неизвестное/неполное состояние (зеркало не читается) → BLOCKED, не ALLOW", ДЕЙСТВИЕ, broken_state, 3)

    shutil.rmtree(база, ignore_errors=True)
    print("=== ИТОГ ПРОБ ===")
    for имя, ок in итоги.items():
        print(f"  {'✓' if ок else '✗'} {имя}")
    всё = all(итоги.values())
    print(f"ПРОБ: {sum(итоги.values())} из {len(итоги)} — {'ВСЕ ВЕРНЫ' if всё else 'ЕСТЬ ОШИБКИ'}")
    if улики:
        (улики / "itog-prob.txt").write_text("\n".join(f"{'✓' if ок else '✗'} {имя}" for имя, ок in итоги.items())
                                            + f"\nПРОБ: {sum(итоги.values())} из {len(итоги)}\n", encoding="utf-8")
    return 0 if всё else 1


if __name__ == "__main__":
    sys.exit(главное())
