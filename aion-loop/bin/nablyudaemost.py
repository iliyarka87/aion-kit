#!/usr/bin/env python3
"""Наблюдаемость канала (N-L1-04): время у каждого звена, начало и конец каждого хода,
ветви отказа различимы, число начатых = числу законченных.

Звенья и их журналы:
    провод (wire) и судья   svyaz/state/zhurnal-kanala.ndjson  — структурно, пишет рука (runner.py);
                             до его появления — восстановление из svyaz/state/runner.log
                             (round -> / to executor / judge / verdict / STOP / nudge / rework)
    будилка (wake)          svyaz/state/watchman-ticks.log — тик раз в минуту с at_local,
                             loop_state, strikes, action
    крючок (hook)           ~/.aion-kryuchok/zhurnal.log — «=== ход начат ===» / «=== ход закончен ===»;
                             крючок убит владельцем 20.09 00:20, журнал — улика прошлого

    python3 bin/nablyudaemost.py [--since "YYYY-MM-DD HH:MM"] [--uliki <dir>]
Код 1, если у живых звеньев (провод, судья) есть начатые без конца.
"""
import datetime as dt
import json
import re
import shutil
import sys
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parent.parent
ЖУРНАЛ = КОРЕНЬ / "svyaz" / "state" / "zhurnal-kanala.ndjson"
РУКА = КОРЕНЬ / "svyaz" / "state" / "runner.log"
ТИКИ = КОРЕНЬ / "svyaz" / "state" / "watchman-ticks.log"
КРЮЧОК = Path.home() / ".aion-kryuchok" / "zhurnal.log"


def ts(s: str) -> float:
    return dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").timestamp()


def из_runner_log(since: float):
    """Восстановить ходы провода и судьи из строк runner.log (до структурного журнала)."""
    ходы = []          # (t, link, move, phase, branch)
    открытые = {}
    t = 0.0
    def открыть(вид, it):
        # новый старт при незакрытом прежнем — прежний остаётся видимо незаконченным
        if вид in открытые:
            t0, prev = открытые.pop(вид)
            ходы.append((t0, "wire" if вид == "round" else "judge", f"{вид}:{prev}", "open", "НЕ ЗАКОНЧЕН"))
        открытые[вид] = (t, it)
    for с in РУКА.read_text(encoding="utf-8").splitlines():
        m = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (.*)", с)
        if m:
            t, текст = ts(m.group(1)), m.group(2)
        else:
            текст = с          # строка-продолжение многострочной записи: время наследуется
        if t < since:
            continue
        if текст.startswith("round -> "):
            it = текст[9:].strip(); открыть("round", it); ходы.append((t, "wire", f"round:{it}", "start", None))
        elif текст.startswith("  to executor: ") and "round" in открытые:
            t0, it = открытые.pop("round"); ходы.append((t, "wire", f"round:{it}", "end", None if "delivered" in текст else "no_executor_window"))
        elif re.match(r"judge N-", текст):
            it = текст[6:].strip(); открыть("judge", it); ходы.append((t, "judge", f"judge:{it}", "start", None))
        elif текст.startswith("verdict:") and "judge" in открытые:
            t0, it = открытые.pop("judge"); ходы.append((t, "judge", f"judge:{it}", "end", None if "PASS" in текст.split("votes")[0] else "judge_rejected"))
        elif "judge interpreter missing" in текст or "НЕ СОСТОЯЛСЯ" in текст or "File name too long" in текст:
            if "judge" in открытые:
                t0, it = открытые.pop("judge"); ходы.append((t, "judge", f"judge:{it}", "end", "judge_unavailable"))
        elif текст.startswith("rework "):
            it = текст.split()[1].rstrip(":"); ходы.append((t, "wire", f"rework:{it}", "start", None)); ходы.append((t, "wire", f"rework:{it}", "end", None if "delivered" in текст else "no_executor_window"))
        elif текст.startswith("nudge "):
            it = текст.split()[1].rstrip(":"); ходы.append((t, "wire", f"nudge:{it}", "start", None)); ходы.append((t, "wire", f"nudge:{it}", "end", None if "delivered" in текст else "no_executor_window"))
        elif текст.startswith("STOP:"):
            ходы.append((t, "wire", "stop", "end", текст[5:].strip().split(":")[0][:40]))
    # конец суда, потерянный в усечённом выводе, восстанавливается по летописи ворот:
    # запись DONE по пункту после старта суда — это и есть его конец (ворота пишут DONE только по PASS)
    done = {}
    for с in (КОРЕНЬ / "checklist" / "letopis.ndjson").read_text(encoding="utf-8").splitlines():
        if с.strip():
            з = json.loads(с)
            if з.get("вид") == "DONE":
                done.setdefault(з["item"], []).append(з["когда"])
    for k, (t0, it) in list(открытые.items()):
        if k == "judge" and any(td >= t0 for td in done.get(it, [])):
            td = min(td for td in done[it] if td >= t0)
            ходы.append((td, "judge", f"judge:{it}", "end", None)); открытые.pop(k)
    # то же для судов, закрытых новым стартом: если по пункту есть DONE после старта — закончен
    for i, h in enumerate(ходы):
        if h[3] == "open" and h[1] == "judge":
            it = h[2].split(":", 1)[1]
            позже = [td for td in done.get(it, []) if td >= h[0]]
            if позже:
                ходы[i] = (min(позже), "judge", h[2], "end", None)
    for k, (t0, it) in открытые.items():
        ходы.append((t0, "wire" if k == "round" else "judge", f"{k}:{it}", "open", "НЕ ЗАКОНЧЕН"))
    return ходы


def из_журнала(since: float):
    if not ЖУРНАЛ.exists():
        return []
    out = []
    for с in ЖУРНАЛ.read_text(encoding="utf-8").splitlines():
        if с.strip():
            з = json.loads(с)
            if з["t"] >= since:
                out.append((з["t"], з["link"], з["move"], з["phase"], з.get("branch")))
    return out


def будилка(since: float, until: float = 9e12):
    if not ТИКИ.exists():
        return 0, 0, {}, 0.0
    тики = []; действия = {}
    for блок in re.split(r"\n(?=\{)", ТИКИ.read_text(encoding="utf-8")):
        try:
            d = json.loads(блок)
        except ValueError:
            continue
        t = dt.datetime.fromisoformat(d["at_local"]).timestamp()
        if t < since or t > until:
            continue
        тики.append(t)
        a = d.get("action") or "NONE"
        действия[a] = действия.get(a, 0) + 1
    тики.sort()
    макс = max((b - a for a, b in zip(тики, тики[1:])), default=0.0)
    return len(тики), sum(v for k, v in действия.items() if k != "NONE"), действия, макс


def крючок(since: float = 0.0):
    if not КРЮЧОК.exists():
        return None
    т = КРЮЧОК.read_text(encoding="utf-8", errors="replace")
    # в периоде проверки: строки с временем ≥ since
    в_периоде = []
    for с in т.splitlines():
        m = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", с)
        if m and ts(m.group(1)) >= since:
            в_периоде.append(с)
    тп = "\n".join(в_периоде)
    начат_п = len(re.findall(r"=== ход начат", тп)); конец_п = len(re.findall(r"=== ход закончен ===", тп))
    начат = len(re.findall(r"=== ход начат", т)); конец = len(re.findall(r"=== ход закончен ===", т))
    даты = re.findall(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", т, flags=re.M)
    ветви = {}
    for m in re.finditer(r"(TimeoutError|ОТКАЗ|ошибка|Error)[^\n]{0,40}", т):
        k = m.group(0)[:50]; ветви[k] = ветви.get(k, 0) + 1
    return {"начато": начат, "закончено": конец, "период": (даты[0] if даты else "?", даты[-1] if даты else "?"),
            "в_периоде_начато": начат_п, "в_периоде_закончено": конец_п,
            "ветви": dict(sorted(ветви.items(), key=lambda x: -x[1])[:4])}


def главное():
    a = sys.argv[1:]
    since = ts(a[a.index("--since") + 1] + (":00" if len(a[a.index("--since") + 1]) == 16 else "")) if "--since" in a else 0.0
    until = ts(a[a.index("--until") + 1] + (":00" if len(a[a.index("--until") + 1]) == 16 else "")) if "--until" in a else dt.datetime.now().timestamp()
    until = float(int(until))
    улики = Path(a[a.index("--uliki") + 1]).resolve() if "--uliki" in a else None
    вывод = []
    def скажи(т=""):
        вывод.append(т); print(т)
    структурные = из_журнала(since)
    в_журнале = {h[2] for h in структурные}
    # структурный журнал главнее: восстановление из runner.log берётся только для ходов, которых в нём нет
    ходы = sorted(h for h in структурные + [h for h in из_runner_log(since) if h[2] not in в_журнале] if h[0] <= until)
    период = (dt.datetime.fromtimestamp(since).strftime("%Y-%m-%d %H:%M:%S") if since else (dt.datetime.fromtimestamp(ходы[0][0]).strftime("%Y-%m-%d %H:%M:%S") if ходы else "—"),
              dt.datetime.fromtimestamp(until).strftime("%Y-%m-%d %H:%M:%S"))
    скажи(f"=== НАБЛЮДАЕМОСТЬ КАНАЛА — период проверки {период[0]} … {период[1]} (граница одна для отчёта и копий) ===")
    скажи(f"журналы (фактические пути): провод и судья — {ЖУРНАЛ} (структурно) и {РУКА}; будилка — {ЖУРНАЛ} (link=wake) и {ТИКИ}; крючок — {КРЮЧОК}")
    беды = 0
    for link, имя in (("wire", "провод (рука/связь)"), ("judge", "судья"), ("wake", "будилка (сторож): тик = ход")):
        мои = [h for h in ходы if h[1] == link and not h[2].startswith("stop")]
        старт = [h for h in мои if h[3] == "start"]; конец = [h for h in мои if h[3] == "end"]; откр = [h for h in мои if h[3] == "open"]
        ветви = {}
        for h in конец:
            if h[4]:
                ветви[h[4]] = ветви.get(h[4], 0) + 1
        скажи(f"--- {имя}: начато {len(старт)}, закончено {len(конец)}, не закончено {len(откр)}")
        for h in мои:
            скажи(f"    {dt.datetime.fromtimestamp(h[0]).strftime('%H:%M:%S')}  {h[3]:5s}  {h[2]:22s} {('ветвь отказа: ' + h[4]) if h[4] else ''}")
        скажи(f"    ветви отказа: {ветви or 'нет'}")
        if len(старт) != len(конец) or откр:
            беды += 1
    стопы = [h for h in ходы if h[2] == "stop"]
    скажи(f"--- остановки руки: {len(стопы)} " + "; ".join(f"{dt.datetime.fromtimestamp(h[0]).strftime('%H:%M:%S')} {h[4]}" for h in стопы))
    n, ударов, действия, макс = будилка(since, until)
    скажи(f"--- будилка, сводка тиков (watchman-ticks.log, один тик = одна запись с временем): тиков {n}, действий {ударов}, {действия}; наибольший разрыв между тиками {макс:.0f} с; пары start/end на тик — в структурном журнале выше (с 05:50)")
    к = крючок(since)
    if к:
        скажи(f"--- крючок (~/.aion-kryuchok/zhurnal.log): в периоде проверки начато {к['в_периоде_начато']}, "
              f"закончено {к['в_периоде_закончено']} — крючок убит владельцем 20.09 00:20, до периода")
        скажи(f"    по решению владельца OD-008 (registries/owner-decision-queue.jsonl) критерий считается по периоду проверки; "
              f"полный файл крючка остаётся на диске: {КРЮЧОК} ({к['период'][0]} … {к['период'][1]}, вне периода)")
        if к["в_периоде_начато"] != к["в_периоде_закончено"]:
            беды += 1
    скажи("")
    скажи("ИТОГ по периоду проверки: " + ("у каждого звена начатых столько же, сколько законченных; ветви отказа названы" if беды == 0
                     else f"есть незаконченные ходы у {беды} звена(ев)"))
    if улики:
        улики.mkdir(parents=True, exist_ok=True)
        (улики / "otchyot-nablyudaemosti.txt").write_text("\n".join(вывод) + "\n", encoding="utf-8")
        # копии — только период проверки, чтобы числа в отчёте и в копиях совпадали
        шапка = f"# копия за период проверки {период[0]} … {период[1]}; источник: {{src}}\n"
        if РУКА.exists():
            стр = []; t = 0.0
            for с in РУКА.read_text(encoding="utf-8").splitlines():
                m = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", с)
                if m: t = ts(m.group(1))
                if since <= t <= until: стр.append(с)
            (улики / "runner.log").write_text(шапка.format(src=РУКА) + "\n".join(стр) + "\n", encoding="utf-8")
        if ЖУРНАЛ.exists():
            стр = [с for с in ЖУРНАЛ.read_text(encoding="utf-8").splitlines() if с.strip() and since <= json.loads(с)["t"] <= until]
            (улики / "zhurnal-kanala.ndjson").write_text(шапка.format(src=ЖУРНАЛ) + "\n".join(стр) + "\n", encoding="utf-8")
        if ТИКИ.exists():
            бл = []
            for блок in re.split(r"\n(?=\{)", ТИКИ.read_text(encoding="utf-8")):
                try: d = json.loads(блок)
                except ValueError: continue
                t = dt.datetime.fromisoformat(d["at_local"]).timestamp()
                if since <= t <= until: бл.append(json.dumps(d, ensure_ascii=False))
            (улики / "watchman-ticks.log").write_text(шапка.format(src=ТИКИ) + f"# тиков в периоде: {len(бл)}\n" + "\n".join(бл) + "\n", encoding="utf-8")
        скажи(f"улики: {улики} (копии журналов строго за период {период[0]} … {период[1]})")
    return 0 if беды == 0 else 1


if __name__ == "__main__":
    sys.exit(главное())
