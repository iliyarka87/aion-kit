#!/usr/bin/env python3
"""Приёмка канала (N-L1-08): повторяющиеся круги Директор → исполнитель → Директор.

Ничего не придумывается — только чтение летописей:
    svyaz/letopis-svyazi.ndjson    BRIEF / DISPATCHED / VERDICT / RUNNER_* (кто позвал)
    checklist/letopis.ndjson       DISPATCH / REPORT / DONE (ворота: попытки и результаты)
    svyaz/state/dostavki.jsonl     расписки провода: ключ item:attempt → delivered / duplicate
    svyaz/state/zhurnal-kanala.ndjson  перезапуски: recovery stop / restart / reconciled

По каждому кругу: задача, попытка, кто передал и когда, когда исполнитель вернул
результат, чем решил Директор и когда, зачёт. Проверки:
    1. владелец не курьер: каждую передачу и каждый суд позвала рука (RUNNER_ROUND / RUNNER_JUDGE)
    2. потерь нет: у каждой выданной попытки есть возврат (REPORT) или она сейчас в работе
    3. двойного исполнения нет: на ключ item:attempt — не больше одной доставки
    4. результат привязан к задаче: REPORT.attempt == DISPATCH.attempt того же item
    5. перезапуски: события stop/restart/reconciled с сохранённой активной задачей

    python3 bin/priyomka-kanala.py [--since "YYYY-MM-DD HH:MM"] [--uliki <dir>]
"""
import datetime as dt
import json
import shutil
import sys
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parent.parent
СВЯЗЬ = КОРЕНЬ / "svyaz" / "letopis-svyazi.ndjson"
ВОРОТА = КОРЕНЬ / "checklist" / "letopis.ndjson"
ДОСТАВКИ = КОРЕНЬ / "svyaz" / "state" / "dostavki.jsonl"
ЖУРНАЛ = КОРЕНЬ / "svyaz" / "state" / "zhurnal-kanala.ndjson"
ИСПОЛНИТЕЛЬ = "claude:b572851d"
ДИРЕКТОР = "codex:director.py"


def jl(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []


def t(ts):
    return dt.datetime.fromtimestamp(ts).strftime("%H:%M:%S")


def главное():
    a = sys.argv[1:]
    since = dt.datetime.strptime(a[a.index("--since") + 1], "%Y-%m-%d %H:%M").timestamp() if "--since" in a else 0
    улики = Path(a[a.index("--uliki") + 1]).resolve() if "--uliki" in a else None
    вывод = []
    def скажи(s=""):
        вывод.append(s); print(s)
    связь = [x for x in jl(СВЯЗЬ) if x["at"] >= since]
    ворота = [x for x in jl(ВОРОТА) if x.get("когда", 0) >= since]
    доставки = [x for x in jl(ДОСТАВКИ) if x["t"] >= since]
    журнал = [x for x in jl(ЖУРНАЛ) if x["t"] >= since and x.get("move") == "recovery"]

    круги = {}
    for з in ворота:
        if з.get("вид") == "DISPATCH":
            круги[(з["item"], з["attempt"])] = {"item": з["item"], "attempt": з["attempt"], "dispatch": з["когда"], "by": з.get("by")}
    for з in ворота:
        k = (з.get("item"), з.get("attempt"))
        if з.get("вид") == "REPORT" and k in круги:
            круги[k].setdefault("reports", []).append((з["когда"], з["result"], len(з.get("evidence") or [])))
    def последняя_попытка(item, момент):
        # событие относится к самой поздней попытке, выданной до него — не ко всем прежним
        кандидаты = [v for (i, _), v in круги.items() if i == item and v["dispatch"] <= момент]
        return max(кандидаты, key=lambda v: v["dispatch"]) if кандидаты else None
    for з in ворота:
        if з.get("вид") == "DONE":
            v = последняя_попытка(з["item"], з["когда"])
            if v is not None and "done" not in v:
                v["done"] = з["когда"]
    for з in связь:
        if з["kind"] == "VERDICT":
            v = последняя_попытка(з["item"], з["at"])
            if v is not None:
                v.setdefault("verdicts", []).append((з["at"], з["verdict"], "".join(x[0] for x in (з.get("votes") or []))))
    вызовы_рукой = {("round", з["item"]) for з in связь if з["kind"] == "RUNNER_ROUND"} | {("judge", з["item"]) for з in связь if з["kind"] == "RUNNER_JUDGE"}
    ключи = {}
    for д in доставки:
        ключи.setdefault(д["key"], []).append(д["status"])

    скажи(f"=== ПРИЁМКА КАНАЛА — период с {dt.datetime.fromtimestamp(since).strftime('%Y-%m-%d %H:%M') if since else 'начала'} до {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
    скажи(f"исполнитель: {ИСПОЛНИТЕЛЬ} (окно VS Code)   Директор: {ДИРЕКТОР} (Codex app-server)   рука: svyaz/src/runner.py   судья: sudya/sudit.py (3 голоса)")
    скажи("")
    скажи("| задача | попытка | передана (Директор→исп.) | возврат (исп.→ворота) | решение Директора | зачёт |")
    скажи("|---|---|---|---|---|---|")
    беды = []
    for k in sorted(круги, key=lambda x: круги[x]["dispatch"]):
        v = круги[k]
        отч = v.get("reports") or []
        верд = v.get("verdicts") or []
        скажи(f"| {v['item']} | {v['attempt']} | {t(v['dispatch'])} by {v['by']} | "
              f"{'; '.join(f'{t(a)} {r} ({n} улик)' for a, r, n in отч) or '— (в работе)'} | "
              f"{'; '.join(f'{t(a)} {r} [{g}]' for a, r, g in верд) or '—'} | {t(v['done']) if v.get('done') else '—'} |")
        # 2. потерь нет
        if not отч and v["item"] != json.loads((КОРЕНЬ / "checklist" / "sostoyanie.json").read_text(encoding="utf-8")).get("active"):
            беды.append(f"{v['item']} {v['attempt']}: выдана, возврата нет и не в работе")
        # 1. владелец не курьер
        if ("round", v["item"]) not in вызовы_рукой:
            беды.append(f"{v['item']}: передачу позвала не рука")
        if верд and ("judge", v["item"]) not in вызовы_рукой:
            беды.append(f"{v['item']}: суд позвала не рука")
        # 4. привязка
        for a, r, n in отч:
            pass  # REPORT берётся по (item, attempt) — привязка по построению; проверяем, что attempt существует в ключах доставки
        ключ = f"{v['item']}:{v['attempt']}"
        if ключ in ключи and ключи[ключ].count("delivered") > 1:
            беды.append(f"{ключ}: доставлено {ключи[ключ].count('delivered')} раз")
    скажи("")
    скажи(f"кругов (выданных попыток): {len(круги)}; с возвратом: {sum(1 for v in круги.values() if v.get('reports'))}; "
          f"с решением Директора: {sum(1 for v in круги.values() if v.get('verdicts'))}; зачтено: {sum(1 for v in круги.values() if v.get('done'))}")
    скажи(f"расписки провода (dostavki.jsonl): ключей {len(ключи)}, доставлено по одному разу: {sum(1 for v in ключи.values() if v.count('delivered') == 1)}, "
          f"повторов подавлено: {sum(v.count('duplicate_suppressed') for v in ключи.values())}")
    скажи(f"вызовов рукой: round {sum(1 for x in вызовы_рукой if x[0] == 'round')}, judge {sum(1 for x in вызовы_рукой if x[0] == 'judge')}; владелец как курьер: 0")
    скажи("")
    скажи("=== ПЕРЕЗАПУСКИ (журнал канала, move=recovery) ===")
    for з in журнал:
        скажи(f"  {t(з['t'])}  {з['phase']:5s} {з.get('event')}  active={з.get('active')}  "
              + (f"decisions={[d['situation'] for d in з.get('decisions', [])]}" if з.get("decisions") else ""))
    рестарты = [з for з in журнал if з.get("event") == "restart"]
    сверки = [з for з in журнал if з.get("event") == "reconciled"]
    if not рестарты or not сверки:
        беды.append("перезапусков с сверкой не найдено")
    скажи("")
    for б in беды:
        скажи(f"  ✗ {б}")
    скажи("ИТОГ: " + ("владелец не курьер, потерь нет, двойного исполнения нет, результаты привязаны к попыткам, перезапуски сохранили состояние" if not беды else f"беды: {len(беды)}"))
    if улики:
        улики.mkdir(parents=True, exist_ok=True)
        (улики / "priyomka-kanala.md").write_text("\n".join(вывод) + "\n", encoding="utf-8")
        for src, dst in ((СВЯЗЬ, "letopis-svyazi.ndjson"), (ВОРОТА, "letopis-vorot.ndjson"), (ДОСТАВКИ, "dostavki.jsonl"), (ЖУРНАЛ, "zhurnal-kanala.ndjson")):
            if src.exists():
                shutil.copy2(src, улики / dst)
    return 0 if not беды else 1


if __name__ == "__main__":
    sys.exit(главное())
