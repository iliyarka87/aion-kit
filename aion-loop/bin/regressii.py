#!/usr/bin/env python3
"""Отбор регрессионных проверок по слоям (N-L2-06, L2.6).

Четыре слоя:
    direct      прямые пробы изменённой части (по карте «путь → проба»)
    affected    пробы частей, зависящих от изменённой (по карте зависимостей)
    invariants  всегда включённые дешёвые инварианты (registries/invariants.jsonl, цена ≤ ДЁШЕВО с)
    extended    расширенный набор при продвижении: все инварианты, включая дорогие,
                все наборы проб, unittest связи, сверка реестров

Типы изменения и что запускается:
    minor      мелкая правка (документ, улика, текст, реестр-источник)  → direct + invariants
    code       правка инструмента (bin/, svyaz/src/, checklist/)        → direct + affected + invariants
    promotion  продвижение версии (стабильная метка, публикация)       → extended (всё, включая дорогие)
Тип определяется по изменённым путям (git diff --name-only <база>) или задаётся явно.

    python3 bin/regressii.py plan   [--type minor|code|promotion] [--paths a b …]   что запустится и почему
    python3 bin/regressii.py run    [--type …] [--paths …] [--uliki <dir>]         запустить и записать в журнал
Журнал: registries/regressii-zhurnal.ndjson — тип изменения, пути, выбранные слои и пробы, результат, время.
"""
import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parent.parent
ЖУРНАЛ = КОРЕНЬ / "registries" / "regressii-zhurnal.ndjson"
ИНВАРИАНТЫ = КОРЕНЬ / "registries" / "invariants.jsonl"
ДЁШЕВО = 1.0    # секунд: инварианты дешевле этого гоняются всегда

# путь (префикс) → прямые пробы
КАРТА = {
    "bin/aionctl": ["python3 bin/proby-sverki.py", "python3 bin/proby-vorot-izmeneniya.py", "python3 bin/aionctl laws"],
    "state/": ["python3 bin/aionctl reconcile", "python3 bin/aionctl orient --json"],
    "authority.json": ["python3 bin/proby-vlasti.py"],
    "laws.json": ["python3 bin/aionctl laws"],
    "registries/otkazy-novye.jsonl": ["python3 bin/proverka-otkazov.py --proby"],
    "bin/sobrat-otkazy.py": ["python3 bin/proverka-otkazov.py --proby"],
    "bin/proverka-otkazov.py": ["python3 bin/proverka-otkazov.py --proby"],
    "bin/uliki.py": ["python3 bin/uliki.py --proby"],
    "evidence/": ["python3 bin/uliki.py proverit"],
    "bin/dogovor_zadachi.py": ["python3 bin/dogovor_zadachi.py --proby"],
    "bin/markery.py": ["python3 bin/markery.py --proby"],
    "svyaz/src/link.py": ["python3 bin/proby-dostavki.py", "python3 -m unittest discover -s svyaz/tests -q"],
    "svyaz/src/director.py": ["python3 -m unittest discover -s svyaz/tests -q"],
    "svyaz/src/mailqueue.py": ["python3 svyaz/src/mailqueue.py --proby"],
    "svyaz/src/vosstanovlenie.py": ["python3 svyaz/src/vosstanovlenie.py --proby"],
    "svyaz/src/runner.py": ["python3 svyaz/src/vosstanovlenie.py --proby"],
    "svyaz/src/watchman.py": ["python3 -m unittest discover -s svyaz/tests -q"],
    "bin/stabilnoe.py": ["python3 bin/stabilnoe.py vozvrat"],
    "checklist/": ["python3 -m unittest discover -s svyaz/tests -q"],
    "0": ["python3 bin/aionctl reconcile"],          # документы канона 0*.md, 1*.md
    "1": ["python3 bin/aionctl reconcile"],
}
# зависимости: изменил X → затронуты пробы Y
ЗАВИСИМОСТИ = {
    "bin/aionctl": ["python3 bin/proby-vlasti.py", "python3 svyaz/src/vosstanovlenie.py --proby"],
    "svyaz/src/link.py": ["python3 svyaz/src/mailqueue.py --proby"],
    "svyaz/src/director.py": ["python3 bin/dogovor_zadachi.py --proby", "python3 bin/markery.py --proby", "python3 svyaz/src/mailqueue.py --proby"],
    "bin/proverka-otkazov.py": ["python3 bin/proby-vorot-izmeneniya.py"],
    "registries/otkazy-novye.jsonl": ["python3 bin/proby-vorot-izmeneniya.py"],
    "bin/sobrat-otkazy.py": ["python3 bin/proby-vorot-izmeneniya.py"],
    "state/": ["python3 bin/proby-sverki.py"],
}
ВСЕ_НАБОРЫ = ["python3 bin/proby-sverki.py", "python3 bin/proby-vlasti.py", "python3 bin/proverka-otkazov.py --proby",
              "python3 bin/uliki.py --proby", "python3 bin/dogovor_zadachi.py --proby", "python3 bin/markery.py --proby",
              "python3 bin/proby-dostavki.py", "python3 svyaz/src/mailqueue.py --proby", "python3 svyaz/src/vosstanovlenie.py --proby",
              "python3 bin/proby-vorot-izmeneniya.py", "python3 -m unittest discover -s svyaz/tests -q",
              "python3 bin/sobrat-reestry.py --sverka", "python3 bin/stabilnoe.py vozvrat", "python3 bin/aionctl reconcile"]


def инварианты():
    if not ИНВАРИАНТЫ.exists():
        return []
    return [json.loads(l) for l in ИНВАРИАНТЫ.read_text(encoding="utf-8").splitlines() if l.strip()]


def тип_по_путям(пути):
    if any(p.startswith(("bin/", "svyaz/src/", "checklist/", "sync/")) and p.endswith((".py", "aionctl", ".sh")) for p in пути):
        return "code"
    return "minor"


def план(тип, пути):
    слои = {"direct": [], "affected": [], "invariants": [], "extended": []}
    почему = []
    for п in пути:
        for префикс, пробы in КАРТА.items():
            if п.startswith(префикс):
                слои["direct"] += [x for x in пробы if x not in слои["direct"]]
        if тип in ("code", "promotion"):
            for префикс, пробы in ЗАВИСИМОСТИ.items():
                if п.startswith(префикс):
                    слои["affected"] += [x for x in пробы if x not in слои["affected"] and x not in слои["direct"]]
    дешёвые = [i for i in инварианты() if float(i["COST_SECONDS"]) <= ДЁШЕВО]
    дорогие = [i for i in инварианты() if float(i["COST_SECONDS"]) > ДЁШЕВО]
    слои["invariants"] = [i["PROBE"] for i in дешёвые if i["PROBE"] not in слои["direct"] + слои["affected"]]
    почему.append(f"тип {тип}: direct — пробы изменённых путей ({len(слои['direct'])}); "
                  + ("affected — пробы зависимых частей (%d); " % len(слои["affected"]) if тип != "minor" else "affected — не нужен для мелкой правки; ")
                  + f"invariants — дешёвые (≤{ДЁШЕВО} с) всегда ({len(слои['invariants'])}); дорогих инвариантов пропущено {len(дорогие)}"
                  + ("" if тип == "promotion" else f" ({', '.join(i['INVARIANT_ID'] for i in дорогие)}) — они идут при продвижении"))
    if тип == "promotion":
        уже = set(слои["direct"] + слои["affected"] + слои["invariants"])
        слои["extended"] = [x for x in ВСЕ_НАБОРЫ + [i["PROBE"] for i in дорогие] if x not in уже]
        # без дублей, сохранив порядок
        seen = set(); слои["extended"] = [x for x in слои["extended"] if not (x in seen or seen.add(x))]
        почему.append(f"продвижение: extended — все наборы, дорогие инварианты, unittest, сверка реестров, возврат ({len(слои['extended'])})")
    return слои, почему


def запустить(команда):
    t0 = time.time()
    r = subprocess.run(команда.split(), capture_output=True, text=True, cwd=str(КОРЕНЬ), timeout=900)
    вывод = r.stdout + r.stderr
    итог = next((с for с in reversed(вывод.splitlines()) if с.startswith(("ПРОБ", "ИТОГ", "OK", "FAILED", "сходится", "РАСХОЖДЕНИЕ", "полнота", "GATE")) or '"restored"' in с), "")
    ok = r.returncode == 0 and "ЕСТЬ" not in итог and "FAILED" not in итог and "РАСХОЖДЕНИЕ" not in итог
    return {"cmd": команда, "ok": ok, "rc": r.returncode, "seconds": round(time.time() - t0, 1), "line": итог.strip()[:90]}


def главное():
    a = sys.argv[1:]
    if not a or a[0] not in ("plan", "run"):
        print(__doc__); return 2
    тип = a[a.index("--type") + 1] if "--type" in a else None
    пути = []
    if "--paths" in a:
        for x in a[a.index("--paths") + 1:]:
            if x.startswith("--"):
                break
            пути.append(x)
    улики = Path(a[a.index("--uliki") + 1]).resolve() if "--uliki" in a else None
    if not пути and тип != "promotion":
        r = subprocess.run(["git", "diff", "--name-only", "HEAD~1"], capture_output=True, text=True, cwd=str(КОРЕНЬ))
        пути = [p for p in r.stdout.split() if p]
    тип = тип or тип_по_путям(пути)
    слои, почему = план(тип, пути)
    print(f"=== РЕГРЕССИИ ПО СЛОЯМ · тип изменения: {тип} · путей: {len(пути)} ===")
    for п in почему:
        print("  " + п)
    for слой, пробы in слои.items():
        print(f"  [{слой:10s}] {len(пробы)} проб" + (": " + "; ".join(пробы) if пробы else ""))
    if a[0] == "plan":
        return 0
    запись = {"t": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "type": тип, "paths": пути[:30],
              "layers": {k: len(v) for k, v in слои.items()}, "runs": [], "why": почему}
    всего = 0.0; всё_ок = True
    for слой, пробы in слои.items():
        for п in пробы:
            r = запустить(п); r["layer"] = слой
            запись["runs"].append(r); всего += r["seconds"]; всё_ок &= r["ok"]
            print(f"    {слой:10s} {'ok ' if r['ok'] else 'FAIL'} {r['seconds']:6.1f} с  {п}  → {r['line']}")
    запись["total_seconds"] = round(всего, 1); запись["result"] = "PASS" if всё_ок else "FAIL"
    ЖУРНАЛ.parent.mkdir(parents=True, exist_ok=True)
    with ЖУРНАЛ.open("a", encoding="utf-8") as h:
        h.write(json.dumps(запись, ensure_ascii=False) + "\n")
    print(f"ИТОГ: {запись['result']} · проб {len(запись['runs'])} · {всего:.1f} с · журнал {ЖУРНАЛ.relative_to(КОРЕНЬ)}")
    if улики:
        улики.mkdir(parents=True, exist_ok=True)
        with (улики / "zhurnal-zapuskov.ndjson").open("a", encoding="utf-8") as h:
            h.write(json.dumps(запись, ensure_ascii=False) + "\n")
    return 0 if всё_ок else 1


if __name__ == "__main__":
    sys.exit(главное())
