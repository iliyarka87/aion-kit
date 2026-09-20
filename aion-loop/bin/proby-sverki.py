#!/usr/bin/env python3
"""Пробы сверки (N-L0-05): reconcile ловит расхождение каждого вида и закрывает публикацию.

Живой канон не трогается. Делается песочная копия канона (без .git), в ней
поднимается свой git, и в неё по одному вносится контролируемое расхождение:

    документы   — версия Мастера в 05 не равна версии в 01
    git         — незакоммиченная правка в каноне 0*.md
    процессы    — объявлен обязательный процесс, которого нет
    runtime     — желаемый python не тот, которым запущен aionctl
    в полёте    — на доске два пункта в работе

После каждого — `aionctl reconcile` в копии: ждём код 1 и строку DRIFT с именем
области. Чистая копия обязана дать код 0. И последняя проба — сама публикация:
sync-скрипт в копии с расхождением обязан остановиться на validate и записать
в журнал синхрона строку RESULT=VALIDATION_FAILED RECONCILE_DRIFT.

    python3 bin/proby-sverki.py                 прогнать всё, вывод — улика
    python3 bin/proby-sverki.py --uliki <dir>   и сложить улики в папку
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parent.parent
НУЖНОЕ = ["00-START-HERE.md", "01-AION-MASTER.md", "02-PRE-PHASE-00-FACTS.md",
          "03-HANDOFF.md", "04-LEGACY-FOUNDATIONS-TO-MERGE.md", "05-CURRENT-STATE.md",
          "06-PROGRESS-LEDGER.md", "07-AGENT-TRUST-AND-OPERATING-MODEL.md",
          "07-ARCHITECT-INDEPENDENCE-PROTOCOL.md", "08-REVIEW-04-AGAINST-MASTER.md",
          "09-PHASE-00-IMPLEMENTATION-CHECKLIST.md", "10-INDUSTRY-ENGINEERING-BENCHMARK.md",
          ".aion-root", "routes.json", "authority.json", "laws.json", "registries", "bin", "state", "checklist", "sync"]

вывод = []


def скажи(т=""):
    вывод.append(т)
    print(т, flush=True)


def зов(*дов, cwd, env=None):
    окр = dict(os.environ)
    окр.pop("AION_HOME", None)
    okр = окр
    if env:
        okр.update(env)
    р = subprocess.run(list(дов), capture_output=True, text=True, cwd=str(cwd), env=okр)
    return р.returncode, ((р.stdout or "") + (р.stderr or "")).strip()


def копия(куда: Path):
    """Песочный канон: только нужное, свой git, чистый рабочий каталог."""
    if куда.exists():
        shutil.rmtree(куда)
    куда.mkdir(parents=True)
    for имя in НУЖНОЕ:
        src = КОРЕНЬ / имя
        if not src.exists():
            continue
        if src.is_dir():
            shutil.copytree(src, куда / имя, ignore=shutil.ignore_patterns("__pycache__", "*.bak-*"))
        else:
            shutil.copy2(src, куда / имя)
    for ш in (("git", "init", "-q", "-b", "main"), ("git", "add", "-A"),
              ("git", "-c", "user.name=proba", "-c", "user.email=proba@local",
               "commit", "-q", "-m", "песочная копия канона")):
        к, в = зов(*ш, cwd=куда)
        if к != 0:
            raise SystemExit(f"копия не собралась: {' '.join(ш)}: {в[-200:]}")


def сверка(копия_: Path):
    return зов(sys.executable, str(копия_ / "bin" / "aionctl"), "reconcile",
               cwd=копия_, env={"AION_HOME": str(копия_)})


def ждём_drift(имя, копия_, область, зацепка):
    код, в = сверка(копия_)
    строки_drift = [с for с in в.splitlines() if "[DRIFT" in с or "[UNKNOWN" in с]
    поймано = код == 1 and any(f"] {область}:" in с and зацепка in с for с in строки_drift)
    скажи(f"--- проба «{имя}» ---")
    скажи(в)
    скажи(f"код выхода: {код}; ждали 1 и DRIFT «{область}: …{зацепка}…» → "
          f"{'ПОЙМАНО' if поймано else 'НЕ ПОЙМАНО'}")
    скажи()
    return поймано


def главное():
    улики = None
    if "--uliki" in sys.argv:
        улики = Path(sys.argv[sys.argv.index("--uliki") + 1]).resolve()
    база = Path(tempfile.mkdtemp(prefix="proba-sverki-"))
    итоги = {}
    try:
        # 0. чистая копия — сходится
        к = база / "chistaya"; копия(к)
        код, в = сверка(к)
        скажи("--- проба «чистая копия» ---"); скажи(в)
        итоги["чистая → код 0"] = код == 0
        скажи(f"код выхода: {код}; ждали 0 → {'ВЕРНО' if код == 0 else 'НЕВЕРНО'}"); скажи()

        # 1. документы: версия Мастера в 05 ≠ 01
        к = база / "dokumenty"; копия(к)
        п = к / "05-CURRENT-STATE.md"
        т = п.read_text(encoding="utf-8")
        т = re.sub(r"(MASTER_VERSION\s*=\s*)MASTER-", r"\1MASTER-PROBA-", т, count=1)
        п.write_text(т, encoding="utf-8")
        зов("git", "-c", "user.name=p", "-c", "user.email=p@l", "commit", "-qam", "drift docs", cwd=к)
        итоги["документы"] = ждём_drift("документы: версия Мастера 05 ≠ 01", к, "документы", "версия Мастера")

        # 2. git: незакоммиченная правка канона
        к = база / "git"; копия(к)
        with (к / "00-START-HERE.md").open("a", encoding="utf-8") as f:
            f.write("\n<!-- проба: незакоммиченная правка -->\n")
        итоги["git"] = ждём_drift("git: незакоммиченная правка 0*.md", к, "git", "незакоммиченных")

        # 3. процессы: обязательный процесс-призрак
        к = база / "processy"; копия(к)
        ж = json.loads((к / "state" / "zhelaemoe.json").read_text(encoding="utf-8"))
        ж["процессы"]["обязательные"] = [{"имя": "проба-призрак", "образец": "aion-proba-prizrak-XK7"}]
        (к / "state" / "zhelaemoe.json").write_text(json.dumps(ж, ensure_ascii=False, indent=2), encoding="utf-8")
        зов("git", "-c", "user.name=p", "-c", "user.email=p@l", "commit", "-qam", "drift proc", cwd=к)
        итоги["процессы"] = ждём_drift("процессы: объявлен процесс, которого нет", к, "процессы", "проба-призрак")

        # 4. runtime: желаемый python не тот
        к = база / "runtime"; копия(к)
        ж = json.loads((к / "state" / "zhelaemoe.json").read_text(encoding="utf-8"))
        ж["runtime"]["python"] = "3.12"
        (к / "state" / "zhelaemoe.json").write_text(json.dumps(ж, ensure_ascii=False, indent=2), encoding="utf-8")
        зов("git", "-c", "user.name=p", "-c", "user.email=p@l", "commit", "-qam", "drift rt", cwd=к)
        итоги["runtime"] = ждём_drift("runtime: желаемый python 3.12", к, "runtime", "python")

        # 5. в полёте: два пункта в работе
        к = база / "polyot"; копия(к)
        с = json.loads((к / "checklist" / "sostoyanie.json").read_text(encoding="utf-8"))
        готовые = [и for и, п in с["пункты"].items() if п["state"] in ("READY", "LOCKED")]
        for и in готовые[:2]:
            с["пункты"][и]["state"] = "ACTIVE"
        if not с.get("active"):
            с["active"] = готовые[0]
        (к / "checklist" / "sostoyanie.json").write_text(json.dumps(с, ensure_ascii=False, indent=1), encoding="utf-8")
        зов("git", "-c", "user.name=p", "-c", "user.email=p@l", "commit", "-qam", "drift flight", cwd=к)
        итоги["в полёте"] = ждём_drift("в полёте: два пункта ACTIVE", к, "в полёте", "в работе")

        # 6. публикация: sync в копии с расхождением обязан остановиться на validate
        к = база / "publikaciya"; копия(к)
        ж = json.loads((к / "state" / "zhelaemoe.json").read_text(encoding="utf-8"))
        ж["runtime"]["python"] = "3.12"
        (к / "state" / "zhelaemoe.json").write_text(json.dumps(ж, ensure_ascii=False, indent=2), encoding="utf-8")
        состояние = база / "sync-state"; состояние.mkdir()
        код, в = зов("bash", str(к / "sync" / "aion-control-sync.sh"), "selftest", cwd=к,
                     env={"AION_CONTROL_DIR": str(к), "AION_SYNC_STATE_DIR": str(состояние),
                          "AION_SYNC_DEBOUNCE": "0"})
        журнал = (состояние / "sync.log").read_text(encoding="utf-8") if (состояние / "sync.log").exists() else ""
        строка = next((с for с in журнал.splitlines() if "RECONCILE_DRIFT" in с), "")
        скажи("--- проба «публикация остановлена» ---")
        скажи(f"sync код выхода: {код} (ждали 2 = VALIDATION_FAILED)")
        скажи(f"строка журнала синхрона: {строка or '— НЕТ —'}")
        итоги["публикация остановлена"] = код == 2 and "RESULT=VALIDATION_FAILED" in строка and "runtime" in строка
        скажи(f"→ {'ПОЙМАНО' if итоги['публикация остановлена'] else 'НЕ ПОЙМАНО'}"); скажи()
        строка_журнала = строка
    finally:
        shutil.rmtree(база, ignore_errors=True)

    скажи("=== ИТОГ ПРОБ ===")
    for имя, ок in итоги.items():
        скажи(f"  {'✓' if ок else '✗'} {имя}")
    всё = all(итоги.values())
    скажи(f"ПРОБ: {sum(итоги.values())} из {len(итоги)} — {'ВСЕ ПОЙМАНЫ' if всё else 'ЕСТЬ ПРОПУСКИ'}")

    if улики:
        улики.mkdir(parents=True, exist_ok=True)
        (улики / "vyvod-reconcile.txt").write_text("\n".join(вывод) + "\n", encoding="utf-8")
        (улики / "stroka-zhurnala-sinhrona.txt").write_text(
            "Строка журнала синхрона (песочная публикация с расхождением runtime):\n"
            f"{строка_журнала}\n", encoding="utf-8")
        скажи(f"улики: {улики}")
    return 0 if всё else 1


if __name__ == "__main__":
    sys.exit(главное())
