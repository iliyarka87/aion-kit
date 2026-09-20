"""ВОРОТА ЧЕК-ЛИСТА — замок, а не работник.

Держат механически:
  · ровно ОДИН пункт в работе (MAX_ACTIVE = 1);
  · работник возвращает только PASS_CANDIDATE | FAIL | BLOCKED;
  · зачёт DONE ставит ТОЛЬКО контроллер и только после решения Директора
    при наличии требуемых доказательств;
  · пункт нельзя взять, пока все его DEPENDS не DONE — перескок закрыт
    физически, а не на доверии;
  · FAIL и BLOCKED никогда не создают зачёта;
  · находка вне текущего пункта записывается, но НЕ меняет, кто в работе,
    и НЕ выдаёт другой пункт;
  · после DONE называется ровно один следующий — и ничего не выполняется,
    пока Директор не отправит его в работу;
  · PROJECT_COMPLETE только через N-COMPLETE-01.

ВРЕМЯ. Поля времени записываются СПРАВОЧНО. Ворота по ним ничего не
решают: не подгоняют, не проваливают, не закрывают. За временем следит
владелец — так он и распорядился.
"""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

СВОЁ = Path(__file__).parent
ОПРЕДЕЛЕНИЕ = СВОЁ / "opredelenie.json"
СОСТОЯНИЕ = СВОЁ / "sostoyanie.json"
ЛЕТОПИСЬ = СВОЁ / "letopis.ndjson"

РАБОТНИК_МОЖЕТ = ("PASS_CANDIDATE", "FAIL", "BLOCKED")
ДИРЕКТОР = ("director", "validator")
ПОСЛЕДНИЙ = "N-COMPLETE-01"
MAX_ACTIVE = 1


class Отказ(Exception):
    pass


def сейчас():
    п = os.environ.get("AION_VOROTA_NOW")
    return float(п) if п else time.time()


def читать():
    if not (ОПРЕДЕЛЕНИЕ.exists() and СОСТОЯНИЕ.exists()):
        raise Отказ("нет определения или состояния — сперва python3 sobrat.py")
    return (json.loads(ОПРЕДЕЛЕНИЕ.read_text(encoding="utf-8")),
            json.loads(СОСТОЯНИЕ.read_text(encoding="utf-8")))


def писать(с):
    в = СОСТОЯНИЕ.with_suffix(".tmp")
    в.write_text(json.dumps(с, ensure_ascii=False, indent=1) + "\n",
                 encoding="utf-8")
    os.replace(в, СОСТОЯНИЕ)


def записать(вид, **поля):
    строка = {"когда": round(сейчас(), 3), "вид": вид, **поля}
    with ЛЕТОПИСЬ.open("a", encoding="utf-8") as ф:
        ф.write(json.dumps(строка, ensure_ascii=False) + "\n")
    return строка


def пересчитать_готовность(о, с):
    """LOCKED -> READY, когда все зависимости стали DONE. Обратно — никогда."""
    for ид in о["порядок"]:
        п = с["пункты"][ид]
        if п["state"] != "LOCKED":
            continue
        if all(с["пункты"][d]["state"] == "DONE"
               for d in о["пункты"][ид]["depends"]):
            п["state"] = "READY"


def следующий(о, с):
    if с["active"]:
        raise Отказ(f"уже в работе: {с['active']}")
    пересчитать_готовность(о, с)
    для_выдачи = [и for и in о["порядок"]
                  if с["пункты"][и]["state"] in ("READY", "FAIL", "BLOCKED")]
    return для_выдачи[0] if для_выдачи else None


def отправить(о, с, ид, кем):
    if кем not in ДИРЕКТОР:
        raise Отказ(f"в работу отправляет только Директор, не «{кем}»")
    if с["active"]:
        raise Отказ(f"MAX_ACTIVE={MAX_ACTIVE}: уже в работе {с['active']}")
    if ид not in с["пункты"]:
        raise Отказ(f"нет такого пункта: {ид}")
    нет_done = [d for d in о["пункты"][ид]["depends"]
                if с["пункты"][d]["state"] != "DONE"]
    if нет_done:
        raise Отказ(f"{ид} нельзя: зависимости не DONE — {', '.join(нет_done)}")
    п = с["пункты"][ид]
    if п["state"] == "DONE":
        raise Отказ(f"{ид} уже DONE")
    н = len(п["attempts"]) + 1
    поп = {"attempt_id": "A-" + hashlib.sha1(f"{ид}#{н}".encode()).hexdigest()[:12],
           "n": н, "started_at": round(сейчас(), 3), "finished_at": None,
           "elapsed_seconds": None, "result": None, "evidence": [],
           "spravochnyy_srok_min": о["пункты"][ид]["spravochnyy_srok_min"]}
    п["attempts"].append(поп)
    п["state"] = "ACTIVE"
    с["active"] = ид
    писать(с)
    записать("DISPATCH", item=ид, attempt=поп["attempt_id"], by=кем)
    return поп


def отчитаться(о, с, исход, улики, кем):
    if исход not in РАБОТНИК_МОЖЕТ:
        raise Отказ(f"работник возвращает только {'/'.join(РАБОТНИК_МОЖЕТ)}, "
                    f"не «{исход}»")
    ид = с["active"]
    if not ид:
        raise Отказ("в работе никого нет")
    п = с["пункты"][ид]
    поп = п["attempts"][-1]
    поп["finished_at"] = round(сейчас(), 3)
    поп["elapsed_seconds"] = round(поп["finished_at"] - поп["started_at"], 1)
    поп["result"] = исход
    поп["evidence"] = list(улики or [])
    п["state"] = исход
    if исход in ("FAIL", "BLOCKED"):
        с["active"] = None
    писать(с)
    записать("REPORT", item=ид, attempt=поп["attempt_id"], result=исход,
             by=кем, evidence=поп["evidence"],
             elapsed_seconds=поп["elapsed_seconds"])
    return поп


def зачесть(о, с, ид, улики, кем):
    """DONE пишет только контроллер — здесь — и только по решению Директора."""
    if кем not in ДИРЕКТОР:
        raise Отказ(f"решение о зачёте принимает только Директор, не «{кем}»")
    if ид not in с["пункты"]:
        raise Отказ(f"нет такого пункта: {ид}")
    п = с["пункты"][ид]
    if п["state"] != "PASS_CANDIDATE":
        raise Отказ(f"{ид} сейчас {п['state']}: зачесть можно только "
                    f"PASS_CANDIDATE")
    if not улики:
        raise Отказ(f"{ид}: без доказательств зачёта нет "
                    f"(требуется: {о['пункты'][ид]['required_evidence'] or '—'})")
    п["state"] = "DONE"
    п["evidence"] = list(улики)
    п["done_by"] = кем
    с["active"] = None
    пересчитать_готовность(о, с)
    писать(с)
    записать("DONE", item=ид, by=кем, evidence=list(улики))
    сл = следующий(о, с)
    записать("NEXT_READY", item=сл)
    return сл


def находка(о, с, текст, кем):
    """Находка вне текущего пункта. Записывается — и только."""
    зап = {"когда": round(сейчас(), 3), "кем": кем, "что": текст,
           "при_каком_пункте": с["active"]}
    с["находки"].append(зап)
    писать(с)
    записать("FINDING", by=кем, text=текст, while_item=с["active"])
    return зап


def завершён(с):
    return с["пункты"][ПОСЛЕДНИЙ]["state"] == "DONE"


ЗНАЧКИ = {"DONE": "✓", "ACTIVE": "▶", "READY": "○", "LOCKED": "·",
          "PASS_CANDIDATE": "?", "FAIL": "✗", "BLOCKED": "✗"}


def время_словами(t):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))


def доска(о, с):
    """Одна строка, по которой всё видно."""
    по = {}
    for и in о["порядок"]:
        т = с["пункты"][и]["state"]
        по[т] = по.get(т, 0) + 1
    print(f"{о['пунктов']} ВСЕГО | {по.get('DONE', 0)} DONE | "
          f"{по.get('ACTIVE', 0)} ACTIVE | {по.get('READY', 0)} READY | "
          f"{по.get('LOCKED', 0)} LOCKED"
          + (f" | {по.get('FAIL', 0)} FAIL" if по.get("FAIL") else "")
          + (f" | {по.get('BLOCKED', 0)} BLOCKED" if по.get("BLOCKED") else "")
          + (f" | {по.get('PASS_CANDIDATE', 0)} НА ПРОВЕРКЕ"
             if по.get("PASS_CANDIDATE") else ""))
    print(f"ACTIVE: {с['active'] or '—'}")
    сохр = с["active"]
    if not сохр:
        с_копия = json.loads(json.dumps(с))
        пересчитать_готовность(о, с_копия)
        готовы = [и for и in о["порядок"]
                  if с_копия["пункты"][и]["state"] in ("READY", "FAIL", "BLOCKED")]
        print(f"NEXT:   {готовы[0] if готовы else '—'}")
    else:
        print("NEXT:   — (сперва закончить текущий)")
    if с["находки"]:
        print(f"находок записано: {len(с['находки'])}")
    print(f"PROJECT_COMPLETE: {завершён(с)}")


def главное(дов):
    if not дов:
        print(__doc__)
        return 2
    к = дов[0]
    о, с = читать()
    улики = [д for i, д in enumerate(дов) if i and дов[i - 1] == "--evidence"]
    кем = дов[дов.index("--by") + 1] if "--by" in дов else "worker"

    if к == "status":
        доска(о, с)
        return 0
    if к == "list":
        ширина = max(len(о["пункты"][и]["имя"]) for и in о["порядок"])
        for и in о["порядок"]:
            т = с["пункты"][и]["state"]
            зн = ЗНАЧКИ.get(т, " ")
            зав = ",".join(о["пункты"][и]["depends"]) or "—"
            print(f"  {зн} {и:<16} {т:<14} {о['пункты'][и]['имя'][:ширина]}"
                  f"   ← {зав}")
        print()
        доска(о, с)
        return 0
    if к == "current":
        if not с["active"]:
            print("в работе никого")
            сл = следующий(о, с)
            print(f"следующий готовый: {сл or '—'}")
            return 0
        ид = с["active"]
        п = с["пункты"][ид]
        поп = п["attempts"][-1]
        оп = о["пункты"][ид]
        print(f"в работе:  {ид} · {оп['имя']}")
        print(f"попытка:   {поп['attempt_id']}  №{поп['n']}")
        print(f"риск:      {оп['risk']}  (справочно {поп['spravochnyy_srok_min']} мин)")
        print(f"начато:    {время_словами(поп['started_at'])}")
        print(f"нужны улики: {оп['required_evidence'] or '—'}")
        print(f"приёмка:   {(оп['acceptance'] or '—')[:150]}")
        return 0
    if к == "history":
        сколько = int(дов[1]) if len(дов) > 1 and дов[1].isdigit() else 20
        if not ЛЕТОПИСЬ.exists():
            print("летопись пуста — ничего не делалось")
            return 0
        строки = ЛЕТОПИСЬ.read_text(encoding="utf-8").splitlines()[-сколько:]
        for с_ in строки:
            з = json.loads(с_)
            хвост = " ".join(f"{к_}={в_}" for к_, в_ in з.items()
                             if к_ not in ("когда", "вид"))
            print(f"  {время_словами(з['когда'])}  {з['вид']:<12} {хвост[:120]}")
        return 0
    if к == "next-ready":
        сл = следующий(о, с)
        print(сл or "НЕТ ГОТОВЫХ")
        return 0 if сл else 1
    if к == "dispatch":
        поп = отправить(о, с, дов[1], кем)
        print(f"в работу: {дов[1]}  попытка {поп['attempt_id']}  "
              f"(справочно {поп['spravochnyy_srok_min']} мин)")
        return 0
    if к == "report":
        поп = отчитаться(о, с, дов[1], улики, кем)
        print(f"исход: {поп['result']}  за {поп['elapsed_seconds']} с")
        return 0
    if к == "validate":
        сл = зачесть(о, с, дов[1], улики, кем)
        print(f"{дов[1]} -> DONE")
        print(f"следующий готовый: {сл or 'НЕТ'}")
        return 0
    if к == "finding":
        з = находка(о, с, дов[1], кем)
        print(f"находка записана (при пункте {з['при_каком_пункте'] or '—'}); "
              f"в работе по-прежнему {с['active'] or '—'}")
        return 0
    if к == "complete":
        print("PROJECT_COMPLETE" if завершён(с) else f"НЕЛЬЗЯ: {ПОСЛЕДНИЙ} не DONE")
        return 0 if завершён(с) else 1
    print(f"не знаю команды: {к}")
    return 2


if __name__ == "__main__":
    try:
        sys.exit(главное(sys.argv[1:]))
    except Отказ as e:
        print(f"ОТКАЗ: {e}")
        sys.exit(3)
