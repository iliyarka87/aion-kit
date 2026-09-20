#!/usr/bin/env python3
"""Семейства отказов и запрет хождения по кругу (N-L2-07, L2.8).

Повторяющиеся ошибки группируются по корню (FAILURE_FAMILY реестра отказов). У каждого
семейства — счётчик повторов и порог: после ТРЕТЬЕГО повтора местные заплатки
запрещены, работа переходит в диагностику, нужна новая проверяемая гипотеза.
Переход виден в журнале (время, семейство, счётчик, причина) и держится воротами:
`aionctl gate` блокирует действие по семейству в диагностике, пока гипотеза не записана.

    python3 bin/semeystva.py sobrat                        реестр семейств из failures.jsonl (+ повторы)
    python3 bin/semeystva.py povtor <СЕМЕЙСТВО> "<что случилось>"   зарегистрировать повтор; 3-й → переход
    python3 bin/semeystva.py gipoteza <СЕМЕЙСТВО> "<диагностика>" "<новая проверяемая гипотеза>"
    python3 bin/semeystva.py proverit <СЕМЕЙСТВО>          можно ли местную заплатку: ALLOW / BLOCKED
    python3 bin/semeystva.py --proby [--uliki <dir>]

Файлы: registries/semeystva.jsonl (семейства, счётчики, состояние),
       registries/semeystva-povtory.ndjson (каждый повтор), registries/perehody-diagnostiki.ndjson (переходы).
"""
import datetime as dt
import json
import sys
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parent.parent
ОТКАЗЫ = КОРЕНЬ / "registries" / "failures.jsonl"
СЕМЕЙСТВА = КОРЕНЬ / "registries" / "semeystva.jsonl"
ПОВТОРЫ = КОРЕНЬ / "registries" / "semeystva-povtory.ndjson"
ПЕРЕХОДЫ = КОРЕНЬ / "registries" / "perehody-diagnostiki.ndjson"
ПОРОГ = 3


def jl(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []


def сейчас():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def собрать(записать=True, отказы=ОТКАЗЫ, повторы=ПОВТОРЫ, переходы=ПЕРЕХОДЫ, семейства=СЕМЕЙСТВА) -> list:
    группы = {}
    for з in jl(отказы):
        f = з.get("FAILURE_FAMILY") or "?"
        g = группы.setdefault(f, {"FAMILY": f, "MEMBERS": [], "ROOT_CAUSE": None, "causes": []})
        g["MEMBERS"].append(з["FAILURE_ID"])
        if з.get("CAUSE_IF_PROVEN"):
            g["causes"].append(з["CAUSE_IF_PROVEN"][:120])
    for r in jl(повторы):
        g = группы.setdefault(r["family"], {"FAMILY": r["family"], "MEMBERS": [], "ROOT_CAUSE": None, "causes": []})
        g.setdefault("REPEATS", []).append(r)
    гипотезы = {}
    for п in jl(переходы):
        гипотезы[п["family"]] = п
    out = []
    for f, g in sorted(группы.items()):
        n = len(g["MEMBERS"]) + len(g.get("REPEATS", []))
        последний = гипотезы.get(f)
        if f.islower():
            # метка старого реестра происшествий (prichina / vypusk / ohrana …) — это тип записи, не корень;
            # группировка по корню для них не сделана, честно помечается и порогом не считается
            состояние = "LEGACY_LABEL"
        elif n >= ПОРОГ:
            состояние = "HYPOTHESIS_SET" if (последний and последний.get("hypothesis")) else "DIAGNOSIS_REQUIRED"
        else:
            состояние = "LOCAL_FIXES_ALLOWED"
        out.append({"FAMILY": f, "ROOT_CAUSE": (max(set(g["causes"]), key=g["causes"].count) if g["causes"] else None),
                    "COUNT": n, "THRESHOLD": ПОРОГ, "STATE": состояние, "MEMBERS": g["MEMBERS"],
                    "REPEATS": [r["t"] for r in g.get("REPEATS", [])],
                    "HYPOTHESIS": (последний or {}).get("hypothesis"), "DIAGNOSIS": (последний or {}).get("diagnosis")})
    if записать:
        семейства.write_text("".join(json.dumps(з, ensure_ascii=False) + "\n" for з in out), encoding="utf-8")
    return out


def повтор(семья: str, что: str, повторы=ПОВТОРЫ, переходы=ПЕРЕХОДЫ, **k) -> dict:
    with повторы.open("a", encoding="utf-8") as h:
        h.write(json.dumps({"t": сейчас(), "family": семья, "what": что}, ensure_ascii=False) + "\n")
    сем = next((s for s in собрать(повторы=повторы, переходы=переходы, **k) if s["FAMILY"] == семья), None)
    if сем and сем["COUNT"] >= ПОРОГ and сем["STATE"] == "DIAGNOSIS_REQUIRED":
        # переход один: пока по семейству висит DIAGNOSIS без гипотезы, новые повторы его не плодят
        последний = next((п for п in reversed(jl(переходы)) if п["family"] == семья), None)
        if not (последний and последний.get("state") == "DIAGNOSIS" and not последний.get("hypothesis")):
            переход = {"t": сейчас(), "family": семья, "count": сем["COUNT"], "threshold": ПОРОГ,
                       "reason": f"{сем['COUNT']}-й повтор семейства «{семья}»: {что}",
                       "state": "DIAGNOSIS", "diagnosis": None, "hypothesis": None,
                       "rule": "местные заплатки запрещены до записанной диагностики и новой проверяемой гипотезы (L2.8)"}
            with переходы.open("a", encoding="utf-8") as h:
                h.write(json.dumps(переход, ensure_ascii=False) + "\n")
            print(f"ПЕРЕХОД В ДИАГНОСТИКУ: {семья} — повтор {сем['COUNT']} ≥ {ПОРОГ}; заплатки запрещены, нужна гипотеза")
            return переход
    print(f"повтор записан: {семья} — счётчик {сем['COUNT'] if сем else '?'} из {ПОРОГ}")
    return {"family": семья, "count": сем["COUNT"] if сем else None}


def гипотеза(семья: str, диагностика: str, гип: str, переходы=ПЕРЕХОДЫ, **k) -> dict:
    запись = {"t": сейчас(), "family": семья, "count": next((s["COUNT"] for s in собрать(переходы=переходы, **k) if s["FAMILY"] == семья), None),
              "threshold": ПОРОГ, "reason": "диагностика проведена", "state": "HYPOTHESIS", "diagnosis": диагностика, "hypothesis": гип,
              "rule": "заплатки разрешены только под этой гипотезой; её опровержение — снова диагностика"}
    with переходы.open("a", encoding="utf-8") as h:
        h.write(json.dumps(запись, ensure_ascii=False) + "\n")
    собрать(переходы=переходы, **k)
    print(f"гипотеза записана: {семья} → HYPOTHESIS_SET")
    return запись


def проверить(семья: str, семейства=СЕМЕЙСТВА) -> int:
    сем = next((s for s in jl(семейства) if s["FAMILY"] == семья), None)
    if not сем:
        print(f"ALLOW   семейство «{семья}» реестру неизвестно (счётчик 0)"); return 0
    if сем["STATE"] == "DIAGNOSIS_REQUIRED":
        print(f"BLOCKED семейство «{семья}»: повторов {сем['COUNT']} ≥ {ПОРОГ} — местная заплатка запрещена, нужна диагностика и гипотеза (semeystva.py gipoteza)")
        return 3
    print(f"ALLOW   семейство «{семья}»: {сем['STATE']}, повторов {сем['COUNT']}" + (f"; гипотеза: {сем['HYPOTHESIS'][:80]}" if сем.get("HYPOTHESIS") else ""))
    return 0


def пробы(улики: Path = None) -> int:
    import shutil, tempfile
    вывод = []
    def скажи(т=""):
        вывод.append(т); print(т)
    б = Path(tempfile.mkdtemp(prefix="proba-semeystv-"))
    o, p, x, s = б / "failures.jsonl", б / "povtory.ndjson", б / "perehody.ndjson", б / "semeystva.jsonl"
    o.write_text(json.dumps({"FAILURE_ID": "F-1", "FAILURE_FAMILY": "PROBA_FAMILY", "CAUSE_IF_PROVEN": "корень: один и тот же"}, ensure_ascii=False) + "\n", encoding="utf-8")
    k = dict(отказы=o, повторы=p, переходы=x, семейства=s)
    итоги = {}
    import io, contextlib
    def cap(f, *a, **kw):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            r = f(*a, **kw)
        return r, buf.getvalue().strip()
    собрать(**k)
    r, t = cap(проверить, "PROBA_FAMILY", s); скажи(f"--- 1 запись: {t}"); итоги["1. одна запись → заплатки разрешены"] = r == 0
    r, t = cap(повтор, "PROBA_FAMILY", "второй раз", повторы=p, переходы=x, отказы=o, семейства=s); скажи(f"--- 2-й повтор: {t}")
    r, t = cap(проверить, "PROBA_FAMILY", s); скажи(f"    {t}"); итоги["2. второй повтор → всё ещё разрешены"] = r == 0
    r, t = cap(повтор, "PROBA_FAMILY", "третий раз, та же ошибка", повторы=p, переходы=x, отказы=o, семейства=s); скажи(f"--- 3-й повтор: {t}")
    итоги["3. третий повтор → ПЕРЕХОД В ДИАГНОСТИКУ записан"] = "ПЕРЕХОД" in t and any(z.get("state") == "DIAGNOSIS" for z in jl(x))
    r, t = cap(проверить, "PROBA_FAMILY", s); скажи(f"    {t}"); итоги["4. после перехода местная заплатка → BLOCKED"] = r == 3
    r, t = cap(повтор, "PROBA_FAMILY", "четвёртый раз", повторы=p, переходы=x, отказы=o, семейства=s); скажи(f"--- 4-й повтор: {t}")
    итоги["5. повторный круг заплаток не продолжается: по-прежнему BLOCKED, второй переход не плодится"] = cap(проверить, "PROBA_FAMILY", s)[0] == 3 and sum(1 for z in jl(x) if z.get("state") == "DIAGNOSIS") == 1
    r, t = cap(гипотеза, "PROBA_FAMILY", "корень: проверка шла по копии, а не по живому", "если пробу гонять по живому пути, ошибка воспроизводится и ловится до сдачи", переходы=x, отказы=o, повторы=p, семейства=s); скажи(f"--- гипотеза: {t}")
    r, t = cap(проверить, "PROBA_FAMILY", s); скажи(f"    {t}"); итоги["6. диагностика + гипотеза записаны → работа под гипотезой разрешена"] = r == 0
    скажи("--- журнал переходов (песочница):")
    for z in jl(x):
        скажи("    " + json.dumps(z, ensure_ascii=False)[:200])
    скажи("=== ИТОГ ПРОБ ===")
    for имя, ок in итоги.items():
        скажи(f"  {'✓' if ок else '✗'} {имя}")
    всё = all(итоги.values())
    скажи(f"ПРОБ: {sum(итоги.values())} из {len(итоги)} — {'ВСЕ ВЕРНЫ' if всё else 'ЕСТЬ ОШИБКИ'}")
    if улики:
        улики.mkdir(parents=True, exist_ok=True)
        (улики / "vyvod-prob.txt").write_text("\n".join(вывод) + "\n", encoding="utf-8")
    shutil.rmtree(б, ignore_errors=True)
    return 0 if всё else 1


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        print(__doc__); sys.exit(2)
    if a[0] == "--proby":
        d = Path(a[a.index("--uliki") + 1]).resolve() if "--uliki" in a else None
        sys.exit(пробы(d))
    if a[0] == "sobrat":
        s = собрать(); print(f"семейств: {len(s)}; в диагностике: {[x['FAMILY'] for x in s if x['STATE'] == 'DIAGNOSIS_REQUIRED']}"); sys.exit(0)
    if a[0] == "povtor":
        r = повтор(a[1], a[2]); sys.exit(0)
    if a[0] == "gipoteza":
        гипотеза(a[1], a[2], a[3]); sys.exit(0)
    if a[0] == "proverit":
        sys.exit(проверить(a[1]))
    print(__doc__); sys.exit(2)
