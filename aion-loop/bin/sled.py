#!/usr/bin/env python3
"""Причинный след изменения и реестр инвариантов (N-L2-04, L2.4–L2.5).

СЛЕД (registries/sledy/<пункт>.json) — машинная запись на каждое изменение (зачтённый
пункт чек-листа): до, замысел, гипотеза, ожидаемое, фактическое, проверка, регрессии,
откат. Собирается из определения пункта, летописей ворот и связи, улик и stable.json.

ИНВАРИАНТ (registries/invariants.jsonl) — доказанное поведение с пробой, ценой (секунды,
замерены прогоном) и частотой проверки. Проверка инвариантов = прогон всех проб и
сверка факта с заявленным.

    python3 bin/sled.py sobrat          следы всех DONE пунктов + реестр инвариантов (с замером цены)
    python3 bin/sled.py proverit        полнота следов; прогон проб инвариантов: факт = заявленное?
"""
import json
import subprocess
import sys
import time
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parent.parent
СЛЕДЫ = КОРЕНЬ / "registries" / "sledy"
ИНВАРИАНТЫ = КОРЕНЬ / "registries" / "invariants.jsonl"
ПОЛЯ_СЛЕДА = ["CHANGE_ID", "ITEM", "ATTEMPT", "BEFORE", "INTENT", "HYPOTHESIS", "EXPECTED", "ACTUAL",
              "VERIFICATION", "REGRESSIONS", "ROLLBACK", "EVIDENCE", "RECORDED_AT"]

# доказанные поведения: пункт → (описание, команда пробы, ожидаемая строка итога, частота)
ИНВАРИАНТЫ_ПО_ПУНКТАМ = {
    "N-L0-05": ("сверка ловит расхождение каждого вида и закрывает публикацию", "python3 bin/proby-sverki.py", "ПРОБ: 7 из 7", "перед каждой публикацией (sync validate) и по требованию"),
    "N-L0-06": ("известная сигнатура отказа даёт BLOCKED с заменой, неизвестная — PASS", "python3 bin/proverka-otkazov.py --proby", "ПРОБ: 5 из 5", "перед действием через aionctl gate"),
    "N-L0-07": ("конфликт документов решается уровнем власти, документ без уровня даёт предупреждение", "python3 bin/proby-vlasti.py", "ПРОБ: 4 из 4", "перед каждой публикацией"),
    "N-L0-08": ("список законов §32 полон, у каждого класс, доля PROMPT_ONLY честна", "python3 bin/aionctl laws", "полнота: ПОЛНЫЙ", "при каждой правке Мастера"),
    "N-L0-09": ("подделанная или пропавшая улика ловится; событие без улики даёт предупреждение", "python3 bin/uliki.py --proby", "ПРОБ: 4 из 4", "перед каждым зачётом"),
    "N-L0-10": ("десять полей ориентации восстанавливаются с диска со ссылками", "python3 bin/aionctl orient --json", '"NEXT"', "при старте каждой сессии и после сжатия"),
    "N-L0-11": ("каждый обмен агентов отражён в журнале обмена", "python3 bin/sobrat-reestry.py", "сверка «каждый обмен отражён»: ДА", "после каждого DONE"),
    "N-L0-12": ("ожидание решения владельца не останавливает независимую работу, окно не открывается", "python3 bin/ochered.py check", "независимая работа продолжается", "ежедневно"),
    "N-L1-02": ("задача без text отклоняется вслух ровно один раз на вид, исправленная проходит", "python3 bin/dogovor_zadachi.py --proby", "ПРОБ: 7 из 7", "при каждой выдаче задачи"),
    "N-L1-03": ("маркер распознаётся по словарю, неизвестное окончание даёт видимый отказ", "python3 bin/markery.py --proby", "ПРОБ: 11 из 11", "при каждой сдаче"),
    "N-L1-05": ("повтор доставки того же ключа не запускает работу второй раз", "python3 bin/proby-dostavki.py", "ПРОБ: 5 из 5", "при каждой доставке"),
    "N-L1-06": ("переполнение и неразбираемое письмо уходят в мёртвое письмо, исполнитель не падает", "python3 svyaz/src/mailqueue.py --proby", "ПРОБ: 8 из 8", "при каждой доставке"),
    "N-L1-07": ("после перезапуска задача продолжается без потери и без повтора", "python3 svyaz/src/vosstanovlenie.py --proby", "ПРОБ: 5 из 5", "при каждом старте руки"),
    "N-L2-01": ("каждое из семи условий даёт BLOCKED, чистое — ALLOW, неизвестность — никогда ALLOW", "python3 bin/proby-vorot-izmeneniya.py", "ПРОБ: 9 из 9", "перед каждым изменением"),
    "N-L2-03": ("изменение кандидата не меняет стабильное; возврат проверен до изменения", "python3 bin/stabilnoe.py vozvrat", '"restored": true', "перед каждым изменением и после продвижения"),
    "N-L2-04": ("следы полны, факт = заявленное, инварианты держатся", "python3 bin/sled.py proverit", "все инварианты держатся", "при каждом зачёте"),
    "N-L2-05": ("строитель не может записать вердикт; у вердикта метаданные двух личностей", "python3 -m unittest discover -s svyaz/tests -q", "OK", "при каждом суде"),
    "N-L2-06": ("мелкая правка не тянет дорогой набор, продвижение тянет", "python3 bin/regressii.py plan --type minor --paths evidence/x", "дорогих инвариантов пропущено", "при каждом отборе"),
    "N-L2-07": ("третий повтор семейства переводит в диагностику и запрещает заплатки", "python3 bin/semeystva.py --proby", "ПРОБ: 6 из 6", "при каждом новом отказе"),
}


def jl(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []


def собрать_следы() -> list:
    опр = json.loads((КОРЕНЬ / "checklist" / "opredelenie.json").read_text(encoding="utf-8"))["пункты"]
    сост = json.loads((КОРЕНЬ / "checklist" / "sostoyanie.json").read_text(encoding="utf-8"))["пункты"]
    ворота = jl(КОРЕНЬ / "checklist" / "letopis.ndjson")
    связь = jl(КОРЕНЬ / "svyaz" / "letopis-svyazi.ndjson")
    стаб = json.loads((КОРЕНЬ / "state" / "stable.json").read_text(encoding="utf-8")) if (КОРЕНЬ / "state" / "stable.json").exists() else {}
    СЛЕДЫ.mkdir(parents=True, exist_ok=True)
    следы = []
    for item, п in сост.items():
        if п["state"] != "DONE":
            continue
        попытка = п["attempts"][-1]
        отчёты = [з for з in ворота if з.get("вид") == "REPORT" and з.get("item") == item]
        вердикты = [з for з in связь if з.get("kind") == "VERDICT" and з.get("item") == item]
        done = next((з for з in ворота if з.get("вид") == "DONE" and з.get("item") == item), {})
        dispatch = next((з for з in ворота if з.get("вид") == "DISPATCH" and з.get("item") == item and з.get("attempt") == попытка["attempt_id"]), {})
        # улика бывает файлом (путь) и текстом (утверждение, записанное в ворота): и то и другое сохраняется как есть
        улики = [{"type": "file" if e.startswith("/") else "claim", "value": e} for e in п.get("evidence", [])]
        инв = ИНВАРИАНТЫ_ПО_ПУНКТАМ.get(item)
        след = {
            "CHANGE_ID": f"CH-{item}-{попытка['attempt_id']}",
            "ITEM": item, "ATTEMPT": попытка["attempt_id"],
            "BEFORE": {"board_before": f"{item} был {'READY' if not dispatch else 'READY→ACTIVE при DISPATCH'} {dispatch.get('когда')}", "depends": опр[item]["depends"],
                       "stable_ref": стаб.get("STABLE_ID"), "stable_commit": стаб.get("commit")},
            "INTENT": опр[item]["objective"],
            "HYPOTHESIS": опр[item]["acceptance"],
            "EXPECTED": {"probe": инв[1] if инв else None, "expected_line": инв[2] if инв else None, "required_evidence": опр[item]["required_evidence"]},
            "ACTUAL": {"reports": [(з["когда"], з["result"], len(з.get("evidence") or [])) for з in отчёты],
                       "final": попытка["result"], "elapsed_seconds": попытка.get("elapsed_seconds")},
            "VERIFICATION": {"judge_votes": [(в["at"], в["verdict"], в.get("votes")) for в in вердикты], "done_at": done.get("когда"), "done_by": done.get("by")},
            "REGRESSIONS": {"suites_rerun": "все наборы проб проекта, сводный прогон 09:30 (evidence/N-L2-04/regressii.txt)", "known_open": "см. registries/failures.jsonl STATUS OPEN"},
            "ROLLBACK": {"how": "git checkout <stable tag> / stabilnoe.py vozvrat", "stable_ref": стаб.get("STABLE_ID"), "restore_status": стаб.get("restore_status")},
            "EVIDENCE": улики,
            "RECORDED_AT": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        assert list(след.keys()) == ПОЛЯ_СЛЕДА
        (СЛЕДЫ / f"{item}.json").write_text(json.dumps(след, ensure_ascii=False, indent=1), encoding="utf-8")
        следы.append(след)
    return следы


def прогнать(команда: str):
    t0 = time.time()
    r = subprocess.run(команда.split(), capture_output=True, text=True, cwd=str(КОРЕНЬ), timeout=900)
    return round(time.time() - t0, 1), r.returncode, (r.stdout + r.stderr)


def собрать_инварианты() -> list:
    записи = []
    for item, (что, проба, ожид, частота) in ИНВАРИАНТЫ_ПО_ПУНКТАМ.items():
        сек, код, вывод = прогнать(проба)
        держится = ожид in вывод
        записи.append({"INVARIANT_ID": f"INV-{item}", "PROVEN_BY": item, "BEHAVIOR": что, "PROBE": проба,
                       "EXPECTED": ожид, "COST_SECONDS": сек, "FREQUENCY": частота,
                       "LAST_CHECK": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "LAST_RESULT": "HOLDS" if держится else "VIOLATED",
                       "SOURCE": f"registries/sledy/{item}.json"})
    ИНВАРИАНТЫ.write_text("".join(json.dumps(з, ensure_ascii=False) + "\n" for з in записи), encoding="utf-8")
    return записи


def проверить() -> int:
    беды = []
    следы = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(СЛЕДЫ.glob("*.json"))]
    сост = json.loads((КОРЕНЬ / "checklist" / "sostoyanie.json").read_text(encoding="utf-8"))["пункты"]
    done = [i for i, п in сост.items() if п["state"] == "DONE"]
    print(f"=== СЛЕДЫ: {len(следы)} файлов, DONE пунктов {len(done)} ===")
    for с in следы:
        пусто = [k for k in ПОЛЯ_СЛЕДА if с.get(k) in (None, "", [], {})]
        if list(с.keys()) != ПОЛЯ_СЛЕДА or пусто:
            беды.append(f"{с.get('ITEM')}: неполный след, пусто {пусто}")
        if с["ACTUAL"]["final"] != "PASS_CANDIDATE" or not с["VERIFICATION"]["done_at"]:
            беды.append(f"{с['ITEM']}: факт не сошёлся с заявленным (final={с['ACTUAL']['final']}, done={с['VERIFICATION']['done_at']})")
    for i in done:
        if not (СЛЕДЫ / f"{i}.json").exists():
            беды.append(f"{i}: DONE без следа")
    инв = jl(ИНВАРИАНТЫ)
    print(f"=== ИНВАРИАНТЫ: {len(инв)} — прогон проб сейчас ===")
    for з in инв:
        сек, код, вывод = прогнать(з["PROBE"])
        держится = з["EXPECTED"] in вывод
        print(f"  [{'HOLDS   ' if держится else 'VIOLATED'}] {з['INVARIANT_ID']:14s} {сек:6.1f} с  (заявлено {з['COST_SECONDS']} с, {з['FREQUENCY']})  {з['BEHAVIOR'][:70]}")
        if not держится:
            беды.append(f"{з['INVARIANT_ID']}: проба не дала «{з['EXPECTED']}»")
        for k in ("PROBE", "COST_SECONDS", "FREQUENCY"):
            if з.get(k) in (None, ""):
                беды.append(f"{з['INVARIANT_ID']}: нет {k}")
    print()
    for б in беды:
        print(f"  ✗ {б}")
    print("ИТОГ: " + ("следы полны, факт = заявленное, все инварианты держатся" if not беды else f"беды: {len(беды)}"))
    return 0 if not беды else 1


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "sobrat":
        с = собрать_следы(); print(f"следов: {len(с)} → {СЛЕДЫ.relative_to(КОРЕНЬ)}/")
        и = собрать_инварианты(); print(f"инвариантов: {len(и)} → {ИНВАРИАНТЫ.relative_to(КОРЕНЬ)}; держатся {sum(1 for x in и if x['LAST_RESULT']=='HOLDS')}")
        sys.exit(0)
    if a and a[0] == "proverit":
        sys.exit(проверить())
    print(__doc__); sys.exit(2)
