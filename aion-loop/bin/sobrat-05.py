#!/usr/bin/env python3
"""05 из доски (план «Закрепить» п.11): машинный блок в 05-CURRENT-STATE.md между метками
<!-- AUTO:DOSKA --> … <!-- /AUTO:DOSKA -->, собранный из ворот, реестров и стабильного.
Ручные поля 05 (POSITION, MASTER_VERSION, LAST_EVENT_ID …) не трогаются — закон 05 остаётся
законом; блок лишь показывает, что говорит машина, и не даёт снимку стухнуть.
После записи пересобирается машинное зеркало state/current.json (sostoyanie.py --sobrat).

    python3 bin/sobrat-05.py            собрать блок и записать в 05
    python3 bin/sobrat-05.py --sverka   блок в 05 = тому, что собралось бы сейчас?
"""
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parent.parent
П05 = КОРЕНЬ / "05-CURRENT-STATE.md"
НАЧ, КОН = "<!-- AUTO:DOSKA -->", "<!-- /AUTO:DOSKA -->"


def jl(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []


def блок() -> str:
    с = json.loads((КОРЕНЬ / "checklist" / "sostoyanie.json").read_text(encoding="utf-8"))
    опр = json.loads((КОРЕНЬ / "checklist" / "opredelenie.json").read_text(encoding="utf-8"))["пункты"]
    доска = subprocess.run([sys.executable, str(КОРЕНЬ / "checklist" / "vorota.py"), "status"], capture_output=True, text=True).stdout.strip().splitlines()
    done = [(и, п) for и, п in с["пункты"].items() if п["state"] == "DONE"]
    летопись = jl(КОРЕНЬ / "checklist" / "letopis.ndjson")
    когда_done = {з["item"]: з["когда"] for з in летопись if з.get("вид") == "DONE"}
    стаб = json.loads((КОРЕНЬ / "state" / "stable.json").read_text(encoding="utf-8")) if (КОРЕНЬ / "state" / "stable.json").exists() else {}
    очередь = jl(КОРЕНЬ / "registries" / "owner-decision-queue.jsonl")
    ждут = [з for з in очередь if з["STATUS"] == "PENDING"]
    регр = jl(КОРЕНЬ / "registries" / "regressii-zhurnal.ndjson")
    копии = jl(Path.home() / "Backups" / "nightly" / "kopii.ndjson")
    отказы = jl(КОРЕНЬ / "registries" / "failures.jsonl")
    сем = jl(КОРЕНЬ / "registries" / "semeystva.jsonl")
    s = [НАЧ, "## ДОСКА (машинно; собирает bin/sobrat-05.py из ворот, реестров и стабильного — не править руками)", ""]
    s.append(f"    СОБРАНО          = {dt.datetime.now().astimezone().isoformat(timespec='seconds')}")
    s.append(f"    ДОСКА            = {доска[0] if доска else '?'}")
    s.append(f"    В_РАБОТЕ         = {с.get('active') or '—'}")
    s.append(f"    СЛЕДУЮЩИЙ        = {(доска[2].split(':',1)[1].strip() if len(доска) > 2 else '?')}")
    s.append(f"    СТАБИЛЬНОЕ       = {стаб.get('STABLE_ID', '—')} @ {str(стаб.get('commit', ''))[:12]}; возврат: {стаб.get('restore_status', '—')}")
    s.append(f"    РЕШЕНИЙ_ЖДУТ     = {len(ждут)}" + (": " + ", ".join(з['DECISION_ID'] for з in ждут) if ждут else ""))
    s.append(f"    РЕГРЕССИИ        = {regr if (regr := (регр[-1]['result'] + ' ' + регр[-1]['t'] + ' (' + регр[-1]['type'] + ')')) else '—'}" if регр else "    РЕГРЕССИИ        = —")
    s.append(f"    КОПИЯ            = {(копии[-1]['result'] + ' ' + копии[-1]['t'] + ', файлов ' + str(копии[-1]['files'])) if копии else '— (kopiya.py не запускалась)'}")
    s.append(f"    ОТКАЗЫ_В_РЕЕСТРЕ = {len(отказы)}; семейств в диагностике: {[x['FAMILY'] for x in сем if x['STATE'] == 'DIAGNOSIS_REQUIRED'] or 'нет'}")
    s.append("")
    s.append(f"    DONE ({len(done)} из {len(с['пункты'])}):")
    for и, п in done:
        т = dt.datetime.fromtimestamp(когда_done[и]).strftime("%m-%d %H:%M") if и in когда_done else "—"
        s.append(f"      {и:14s} {т}  {опр[и]['имя'][:60]}")
    s.append(КОН)
    return "\n".join(s)


def главное():
    новый = блок()
    т = П05.read_text(encoding="utf-8")
    if НАЧ in т and КОН in т:
        старый = т[т.index(НАЧ):t_end(т)]
        if "--sverka" in sys.argv:
            # сравниваем без строки СОБРАНО (время)
            норм = lambda x: "\n".join(l for l in x.splitlines() if not l.strip().startswith("СОБРАНО"))
            print("сходится" if норм(старый) == норм(новый) else "РАСХОЖДЕНИЕ: блок ДОСКА в 05 отстал — sobrat-05.py")
            return 0 if норм(старый) == норм(новый) else 1
        т = т.replace(старый, новый)
    else:
        if "--sverka" in sys.argv:
            print("РАСХОЖДЕНИЕ: блока ДОСКА в 05 нет"); return 1
        # вставляем перед разделом MASTER (после ручной позиции), чтобы не мешать закону 05
        якорь = "## MASTER"
        т = т.replace(якорь, новый + "\n\n" + якорь, 1) if якорь in т else т + "\n" + новый + "\n"
    П05.write_text(т, encoding="utf-8")
    r = subprocess.run([sys.executable, str(КОРЕНЬ / "state" / "sostoyanie.py"), "--sobrat"], capture_output=True, text=True)
    print(f"05: блок ДОСКА записан; зеркало пересобрано ({'ok' if r.returncode == 0 else 'ОШИБКА: ' + (r.stdout + r.stderr)[-120:]})")
    return 0


def t_end(т):
    return т.index(КОН) + len(КОН)


if __name__ == "__main__":
    sys.exit(главное())
