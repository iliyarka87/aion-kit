"""ДИРЕКТОР — Codex решает, исполнитель строит. Всё на одной машине.

    python3 direktor.py krug        один круг: Codex смотрит доску, даёт
                                    задачу исполнителю, ждёт, судит, ставит
                                    зачёт воротами и называет следующий пункт
    python3 direktor.py reshit      только решение Codex, без отправки
    python3 direktor.py --раз       один круг и выход (то же, что krug)

Ни GitHub, ни браузера, ни почтальона. Codex зовётся местным app-server по
stdio; исполнитель — через почтовый ящик его окна.

ЗАКОНЫ, КОТОРЫЕ ЗДЕСЬ НЕ ОБХОДЯТСЯ:
  · один пункт в работе (ворота);
  · исполнитель возвращает PASS_CANDIDATE / FAIL / BLOCKED, зачёт не ставит;
  · зачёт пишут ворота и только по слову Директора при наличии улик;
  · Директор не строит, исполнитель не судит.
"""
import os
import json
import subprocess
import sys
import time
from pathlib import Path

КОРЕНЬ = Path(os.environ.get("AION_ROOT", ".")).resolve()   # корень канона: AION_ROOT
ЧЕКЛИСТ = КОРЕНЬ / "checklist"
СВЯЗЬ = КОРЕНЬ / "svyaz" / "svyaz.py"
ЛЕТОПИСЬ = КОРЕНЬ / "svyaz" / "letopis-svyazi.ndjson"
CODEX = "/Applications/ChatGPT.app/Contents/Resources/codex"
ПРЕДЕЛ_CODEX = 420


def запись(вид, **поля):
    ЛЕТОПИСЬ.parent.mkdir(parents=True, exist_ok=True)
    с = {"когда": round(time.time(), 1), "вид": вид, **поля}
    with ЛЕТОПИСЬ.open("a", encoding="utf-8") as ф:
        ф.write(json.dumps(с, ensure_ascii=False) + "\n")
    return с


def ворота(*дов):
    р = subprocess.run([sys.executable, "vorota.py", *дов], cwd=ЧЕКЛИСТ,
                       capture_output=True, text=True)
    return р.returncode, ((р.stdout or "") + (р.stderr or "")).strip()


def codex(вопрос):
    """Один ход Codex по протоколу. Только чтение."""
    п = subprocess.Popen([CODEX, "app-server", "--listen", "stdio://"],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, bufsize=1)
    начало, счёт, куски = time.time(), [0], []

    def послать(м, пар):
        счёт[0] += 1
        п.stdin.write(json.dumps({"jsonrpc": "2.0", "id": счёт[0],
                                  "method": м, "params": пар},
                                 ensure_ascii=False) + "\n")
        п.stdin.flush()
        return счёт[0]

    def ждать(усл):
        while time.time() - начало < ПРЕДЕЛ_CODEX:
            с = п.stdout.readline()
            if not с:
                return None
            с = с.strip()
            if not с:
                continue
            try:
                з = json.loads(с)
            except Exception:
                continue
            if усл(з):
                return з
        return None

    try:
        и = послать("initialize", {"clientInfo": {"name": "direktor",
                                                  "title": "Директор",
                                                  "version": "1"}})
        ждать(lambda з: з.get("id") == и)
        и = послать("thread/start", {"cwd": str(КОРЕНЬ), "sandbox": "read-only",
                                     "approvalPolicy": "never", "ephemeral": True})
        о = ждать(lambda з: з.get("id") == и)
        поток = (((о or {}).get("result") or {}).get("thread") or {}).get("id")
        if not поток:
            return ""
        и = послать("turn/start", {"threadId": поток,
                                   "input": [{"type": "text", "text": вопрос}]})

        def конец(з):
            м = з.get("method", "")
            if м == "item/agentMessage/delta":
                куски.append((з.get("params") or {}).get("delta", ""))
            return м.startswith("turn/completed")
        ждать(конец)
    finally:
        try:
            п.stdin.close(); п.terminate(); п.wait(timeout=8)
        except Exception:
            п.kill()
    return "".join(куски).strip()


def доска():
    _, д = ворота("status")
    return д


def решить():
    """Codex смотрит доску и следующий пункт, говорит задание исполнителю."""
    к, сл = ворота("next-ready")
    if к != 0 or not сл.startswith("N-"):
        return None, None, f"ворота не дали пункт: {сл}"
    о = json.loads((ЧЕКЛИСТ / "opredelenie.json").read_text(encoding="utf-8"))
    п = о["пункты"][сл]
    вопрос = (
        "Ty DIREKTOR proekta AION. Ty NE stroish — ty stavish zadachu ispolnitelyu.\n"
        "Prochitay punkt cheklista i napishi ispolnitelyu korotkoe zadanie:\n"
        "chto sdelat, chto schitat priyomkoy, kakie uliki nuzhny faylami.\n"
        "Ne bolshe 12 strok. Pishi po-russki. Nichego ne vypolnyay sam.\n\n"
        f"PUNKT: {сл} · {п['имя']}\n"
        f"CEL: {п['objective']}\n"
        f"PRIYOMKA: {п['acceptance']}\n"
        f"ULIKI: {п['required_evidence']}\n"
        f"NELZYA: {п.get('non_scope', '')[:300]}\n"
        f"RISK: {п['risk']}\n")
    задание = codex(вопрос)
    return сл, задание, ""


def круг():
    доска_до = доска()
    print(доска_до.splitlines()[0])
    сл, задание, беда = решить()
    if not сл:
        print(f"СТОП: {беда}")
        return 1
    print(f"Директор выбрал: {сл}")
    if not задание:
        print("СТОП: Codex не дал задания")
        return 1
    запись("ZADANIE", item=сл, text=задание[:2000])

    к, в = ворота("dispatch", сл, "--by", "director")
    if к != 0:
        print(f"СТОП: ворота не дали в работу — {в}")
        return 1
    print(f"  {в}")

    полный = (f"ЗАДАЧА ОТ ДИРЕКТОРА · пункт {сл}\n\n{задание}\n\n"
              "Когда закончишь — отчитайся через ворота:\n"
              f"  cd {ЧЕКЛИСТ} && python3 vorota.py report PASS_CANDIDATE "
              "--by worker --evidence <улика> ...\n"
              "Зачёт не ставь: его ставит Директор.")
    р = subprocess.run([sys.executable, str(СВЯЗЬ), "komu-claude", полный],
                       capture_output=True, text=True)
    print(f"  исполнителю: {(р.stdout or р.stderr).strip()[:100]}")
    запись("OTDANO", item=сл)
    print("\nЗадача у исполнителя. Как он отчитается — запусти: python3 direktor.py sudit")
    return 0


def судить():
    """Codex судит кандидата и, если PASS, ворота ставят зачёт."""
    с = json.loads((ЧЕКЛИСТ / "sostoyanie.json").read_text(encoding="utf-8"))
    ид = с.get("active")
    if not ид or с["пункты"][ид]["state"] != "PASS_CANDIDATE":
        print(f"судить нечего: active={ид}, "
              f"состояние={с['пункты'][ид]['state'] if ид else '—'}")
        return 1
    поп = с["пункты"][ид]["attempts"][-1]
    о = json.loads((ЧЕКЛИСТ / "opredelenie.json").read_text(encoding="utf-8"))["пункты"][ид]
    вопрос = (
        "Ty NEZAVISIMYY PROVERSHCHIK. Ty ne stroil. Proveryay po FAYLAM, ne po slovam.\n"
        "Otvet strogo:\nVERDICT: PASS\nili\nVERDICT: FAIL\nREASONS:\n- prichina\n"
        "CHECKED:\n- chto sveril\n\n"
        f"PUNKT: {ид} · {о['имя']}\nPRIYOMKA: {о['acceptance']}\n"
        f"TREBUEMYE ULIKI: {о['required_evidence']}\n"
        f"ZAYAVKA ISPOLNITELYA:\n" + "\n".join(f"- {у}" for у in поп.get("evidence", [])))
    ответ = codex(вопрос)
    запись("VERDIKT", item=ид, text=ответ[:2000])
    print(ответ[:800])
    if "VERDICT: PASS" in ответ:
        улики = поп.get("evidence", []) + ["вердикт Codex: PASS"]
        арг = []
        for у in улики:
            арг += ["--evidence", у]
        к, в = ворота("validate", ид, "--by", "director", *арг)
        print(f"\n{в}")
        return 0 if к == 0 else 1
    print("\nзачёт НЕ поставлен — Директор сказал FAIL")
    return 1


if __name__ == "__main__":
    к = sys.argv[1] if len(sys.argv) > 1 else "krug"
    sys.exit({"krug": круг, "--раз": круг, "reshit": lambda: (print(решить()[1] or "—"), 0)[1],
              "sudit": судить}.get(к, lambda: (print(__doc__), 2)[1])())
