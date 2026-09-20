#!/usr/bin/env python3
"""Реестры L0.6 (N-L0-11): DECISION, INCIDENT, PATTERN, METHOD, COMPANY, PRODUCT_MANIFEST
и AI_EXCHANGE_LEDGER по 13 полям §23.

Сборка детерминированна: всё берётся с диска, руками ведутся только три источника
в registries/istochniki/ (решения владельца, факты компании, манифест продуктов).

    decisions.jsonl          решения: owner_decisions из 05 (через state/current.json)
                             + istochniki/resheniya-novye.jsonl
    incidents.jsonl          происшествия: каждая запись реестра отказов с датой = одно
                             происшествие (INC-*, NEW-*), ссылка на FAILURE_ID
    patterns.jsonl           доказанные образцы: каждый DONE пункт чек-листа с уликами
    methods.jsonl            методы: инструменты bin/*.py, svyaz/src/*.py, checklist/*.py
                             — имя, назначение (первая строка docstring), команды
    company.jsonl            istochniki/company.jsonl
    product-manifest.jsonl   istochniki/product-manifest.jsonl
    ai-exchange-ledger.jsonl обмены агентов: BRIEF/DISPATCHED (Директор → исполнитель),
                             REPORT (исполнитель → ворота/Директор), VERDICT (судья →
                             Директор), RUNNER_* (рука). Журнал перевозки
                             (letopis-svyazi.ndjson) сам по себе PASS не доказывает —
                             доказывает запись здесь, и сборка сверяет: у каждого
                             DISPATCHED / REPORT / VERDICT есть своя запись.

    python3 bin/sobrat-reestry.py            собрать
    python3 bin/sobrat-reestry.py --sverka   собранное = лежащему?
"""
import ast
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parent.parent
Р = КОРЕНЬ / "registries"
И = Р / "istochniki"
ПОЛЯ_23 = ["EXCHANGE_ID", "TIMESTAMP", "FROM", "TO", "PURPOSE", "RELATED_PHASE", "RELATED_CHANGE",
           "RELATED_TASK", "PROMPT_REF_OR_HASH", "RESPONSE_REF_OR_HASH", "STATUS", "DECISION", "NEXT_ACTION"]


def jsonl(п: Path):
    if not п.exists():
        return []
    return [json.loads(с) for с in п.read_text(encoding="utf-8").splitlines() if с.strip()]


def сша(т: str) -> str:
    return hashlib.sha256(т.encode("utf-8")).hexdigest()[:16]


def когда(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


def решения():
    тек = json.loads((КОРЕНЬ / "state" / "current.json").read_text(encoding="utf-8"))
    out = []
    for i, d in enumerate(тек.get("owner_decisions") or [], 1):
        ид = d.split()[0] if d.split() else f"D-05-{i:02d}"
        out.append({"DECISION_ID": ид, "WHEN": тек["source"]["updated_at"], "BY": "владелец",
                    "DECISION": d, "SOURCE": "state/current.json → owner_decisions ← 05-CURRENT-STATE.md",
                    "STATUS": "ЗАКРЫТО" if "ЗАКРЫТ" in d else "В СИЛЕ"})
    out += jsonl(И / "resheniya-novye.jsonl")
    return out


def происшествия():
    out = []
    for з in jsonl(Р / "failures.jsonl"):
        if not з["FAILURE_ID"].startswith(("INC-", "NEW-")):
            continue
        out.append({"INCIDENT_ID": з["FAILURE_ID"], "WHEN": з["FIRST_SEEN"], "WHAT": з["REAL_EXAMPLE"],
                    "FAILURE_FAMILY": з["FAILURE_FAMILY"], "FAILURE_REF": "registries/failures.jsonl#" + з["FAILURE_ID"],
                    "EVIDENCE": з["PATH_OR_LOG"], "STATUS": з["STATUS"]})
    return out


def образцы():
    опр = json.loads((КОРЕНЬ / "checklist" / "opredelenie.json").read_text(encoding="utf-8"))["пункты"]
    сост = json.loads((КОРЕНЬ / "checklist" / "sostoyanie.json").read_text(encoding="utf-8"))["пункты"]
    out = []
    for ид, п in сост.items():
        if п["state"] != "DONE":
            continue
        out.append({"PATTERN_ID": "P-" + ид, "NAME": опр[ид]["имя"], "PROVEN_BY": ид,
                    "WHAT": опр[ид]["objective"], "ACCEPTANCE": опр[ид]["acceptance"],
                    "EVIDENCE": [e for e in п.get("evidence", []) if e.startswith("/")],
                    "DONE_BY": п.get("done_by"), "SOURCE": "checklist/sostoyanie.json + opredelenie.json"})
    return out


def методы():
    out = []
    for папка in ("bin", "svyaz/src", "checklist", "state"):
        for ф in sorted((КОРЕНЬ / папка).glob("*.py")) + sorted((КОРЕНЬ / папка).glob("aionctl")):
            try:
                дерево = ast.parse(ф.read_text(encoding="utf-8"))
                док = (ast.get_docstring(дерево) or "").strip()
            except (SyntaxError, ValueError):
                док = ""
            первая = док.splitlines()[0] if док else "(без описания)"
            команды = [с.strip() for с in док.splitlines() if с.strip().startswith(("python3 ", "aionctl "))]
            out.append({"METHOD_ID": "M-" + ф.name.replace(".py", ""), "PATH": str(ф.relative_to(КОРЕНЬ)),
                        "PURPOSE": первая, "COMMANDS": команды[:6], "SOURCE": "docstring файла"})
    return out


def обмены():
    """Одна запись на каждый осмысленный обмен, 13 полей §23."""
    тек = json.loads((КОРЕНЬ / "state" / "current.json").read_text(encoding="utf-8"))
    фаза, изменение = тек.get("current_phase", ""), тек.get("current_change", "")
    out, n = [], 0

    def запись(ts, от, кому, цель, задача, prompt_ref, resp_ref, статус, решение, дальше):
        nonlocal n
        n += 1
        return {"EXCHANGE_ID": f"X-{n:04d}", "TIMESTAMP": когда(ts), "FROM": от, "TO": кому,
                "PURPOSE": цель, "RELATED_PHASE": фаза, "RELATED_CHANGE": изменение,
                "RELATED_TASK": задача, "PROMPT_REF_OR_HASH": prompt_ref, "RESPONSE_REF_OR_HASH": resp_ref,
                "STATUS": статус, "DECISION": решение, "NEXT_ACTION": дальше}

    связь = jsonl(КОРЕНЬ / "svyaz" / "letopis-svyazi.ndjson")
    ворота = jsonl(КОРЕНЬ / "checklist" / "letopis.ndjson")
    события = []
    for з in связь:
        события.append((з["at"], "svyaz", з))
    for з in ворота:
        if з.get("вид") in ("REPORT", "DONE"):
            события.append((з["когда"], "vorota", з))
    события.sort(key=lambda x: x[0])
    бриф = {}
    for ts, ист, з in события:
        if ист == "svyaz":
            k, it = з["kind"], з.get("item", "")
            if k == "BRIEF":
                бриф[it] = з.get("text", "")
            elif k == "DISPATCHED":
                out.append(запись(ts, "Директор (Codex)", "исполнитель (Claude)", "задание по пункту чек-листа", it,
                                  "sha256:" + сша(бриф.get(it, "")) + " (BRIEF в svyaz/letopis-svyazi.ndjson)",
                                  "—", "DELIVERED", "ворота: dispatch", "исполнитель строит и докладывает воротами"))
            elif k == "VERDICT":
                out.append(запись(ts, "судья (три голоса Codex)", "Директор → ворота", "суд по уликам", it,
                                  "улики пункта (checklist/letopis.ndjson REPORT)",
                                  "verdict=" + str(з.get("verdict")) + " votes=" + ",".join(з.get("votes") or []),
                                  "ACCEPTED" if з.get("verdict") == "PASS" else "REJECTED",
                                  str(з.get("verdict")), "validate → DONE" if з.get("verdict") == "PASS" else "причины исполнителю"))
            elif k == "RUNNER_NUDGE":
                out.append(запись(ts, "рука (runner)", "исполнитель (Claude)", "напоминание о докладе", it, "—", "—",
                                  "DELIVERED" if з.get("delivered") else "NOT_DELIVERED", "—", "доложить воротами"))
            elif k == "RUNNER_JUDGE" and з.get("result") == "REJECTED":
                out.append(запись(ts, "рука (runner)", "исполнитель (Claude)", "причины отказа судьи", it, "—",
                                  f"rejection {з.get('n')}", "DELIVERED", "REJECTED", "доработать и сдать заново"))
        else:
            if з.get("вид") == "REPORT":
                улики = з.get("evidence") or []
                out.append(запись(ts, "исполнитель (Claude)", "ворота → Директор", "сдача результата", з["item"],
                                  "задание " + з["item"], "sha256:" + сша(json.dumps(улики, ensure_ascii=False))
                                  + f" ({len(улики)} улик, checklist/letopis.ndjson REPORT {з.get('attempt')})",
                                  з.get("result"), "—", "суд"))
            elif з.get("вид") == "DONE":
                out.append(запись(ts, "ворота", "все", "зачёт", з["item"], "—",
                                  "checklist/letopis.ndjson DONE " + з["item"], "DONE", "DONE by " + str(з.get("by")),
                                  "следующий готовый пункт"))
    return out, связь, ворота


def сверить_обмены(журнал, связь, ворота):
    """Каждый обмен перевозки обязан иметь запись в журнале обмена."""
    беды = []
    по_задаче = {}
    for з in журнал:
        по_задаче.setdefault(з["RELATED_TASK"], []).append(з)
    for з in связь:
        if з["kind"] in ("DISPATCHED", "VERDICT"):
            it = з.get("item")
            нужно = "задание по пункту чек-листа" if з["kind"] == "DISPATCHED" else "суд по уликам"
            if not any(x["PURPOSE"] == нужно for x in по_задаче.get(it, [])):
                беды.append(f"{з['kind']} {it}: нет записи в журнале обмена")
    for з in ворота:
        if з.get("вид") == "REPORT":
            if not any(x["PURPOSE"] == "сдача результата" and x["RESPONSE_REF_OR_HASH"].endswith(f"REPORT {з.get('attempt')})")
                       for x in по_задаче.get(з["item"], [])):
                беды.append(f"REPORT {з['item']} {з.get('attempt')}: нет записи в журнале обмена")
    return беды


def собрать():
    журнал, связь, ворота = обмены()
    для_записи = {
        "decisions.jsonl": решения(),
        "incidents.jsonl": происшествия(),
        "patterns.jsonl": образцы(),
        "methods.jsonl": методы(),
        "company.jsonl": jsonl(И / "company.jsonl"),
        "product-manifest.jsonl": jsonl(И / "product-manifest.jsonl"),
        "ai-exchange-ledger.jsonl": журнал,
    }
    for з in журнал:
        assert list(з.keys()) == ПОЛЯ_23
    тексты = {имя: "".join(json.dumps(з, ensure_ascii=False) + "\n" for з in зап) for имя, зап in для_записи.items()}
    return тексты, сверить_обмены(журнал, связь, ворота), (связь, ворота)


def главное():
    тексты, беды, (связь, ворота) = собрать()
    if "--sverka" in sys.argv:
        расх = [имя for имя, т in тексты.items() if (Р / имя).read_text(encoding="utf-8") != т if (Р / имя).exists()]
        расх += [имя for имя in тексты if not (Р / имя).exists()]
        print("сходится" if not расх else "РАСХОЖДЕНИЕ: " + ", ".join(расх))
        return 0 if not расх else 1
    for имя, т in тексты.items():
        (Р / имя).write_text(т, encoding="utf-8")
        print(f"  {имя:26s} {т.count(chr(10)):4d} записей")
    перевозка = sum(1 for з in связь if з["kind"] in ("DISPATCHED", "VERDICT")) + sum(1 for з in ворота if з.get("вид") == "REPORT")
    print(f"обменов в перевозке (DISPATCHED+VERDICT+REPORT): {перевозка}; записей журнала обмена: {тексты['ai-exchange-ledger.jsonl'].count(chr(10))}")
    print("сверка «каждый обмен отражён»: " + ("ДА" if not беды else "НЕТ — " + "; ".join(беды[:5])))
    return 0 if not беды else 1


if __name__ == "__main__":
    sys.exit(главное())
