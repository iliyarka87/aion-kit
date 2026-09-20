"""Выводит неизменное определение чек-листа и начальное состояние.

Источник — MASTER-CHECKLIST-MIGRATION-1.md. Он НЕ меняется и не
переписывается: только читается. Всё нужное в нём уже есть полями
DEPENDS, RISK, REQUIRED_EVIDENCE, LEVEL, CLASS.

    python3 sobrat.py          собрать определение и начальное состояние
    python3 sobrat.py --сверка  сверить определение обратно с источником

Поля времени сохраняются как СПРАВОЧНЫЕ. Ворота по ним ничего не решают:
владелец следит за временем сам.
"""
import hashlib
import json
import os
import re
import sys
from pathlib import Path

СВОЁ = Path(__file__).parent
# источник чек-листа: свой документ через AION_CHECKLIST_SOURCE, иначе учебный пример рядом
ИСТОЧНИК = Path(os.environ.get("AION_CHECKLIST_SOURCE", СВОЁ / "examples" / "example-checklist.md"))
ОПРЕДЕЛЕНИЕ = СВОЁ / "opredelenie.json"
СОСТОЯНИЕ = СВОЁ / "sostoyanie.json"

СПРАВОЧНЫЕ_СРОКИ = {"GREEN": 20, "YELLOW": 45, "RED": 90}
ПОЛЯ = ("CLASS", "IMPLEMENTATION_MODE", "TASK_STATE", "LEVEL", "DEPENDS",
        "RISK", "REQUIRED_EVIDENCE", "ACCEPTANCE", "INDEPENDENT_REVIEW",
        "OBJECTIVE")


def разобрать():
    текст = ИСТОЧНИК.read_text(encoding="utf-8")
    куски = re.split(r"^### (N-[A-Z0-9-]+) · (.+)$", текст, flags=re.M)
    пункты, порядок = {}, []
    for i in range(1, len(куски), 3):
        ид, имя, тело = куски[i], куски[i + 1].strip(), куски[i + 2]
        п = {"id": ид, "имя": имя}
        for поле in ПОЛЯ:
            м = re.search(rf"^- {поле}: (.+)$", тело, flags=re.M)
            п[поле.lower()] = м.group(1).strip() if м else ""
        зав = п["depends"]
        п["depends"] = ([] if not зав or зав.upper() in ("НЕТ", "—", "-")
                        else re.findall(r"N-[A-Z0-9-]+", зав))
        риск = (п["risk"] or "GREEN").upper().split()[0]
        п["risk"] = риск if риск in СПРАВОЧНЫЕ_СРОКИ else "GREEN"
        # СПРАВОЧНО, ворота этим не пользуются
        п["spravochnyy_srok_min"] = СПРАВОЧНЫЕ_СРОКИ[п["risk"]]
        пункты[ид] = п
        порядок.append(ид)
    return пункты, порядок


def собрать():
    пункты, порядок = разобрать()
    опр = {
        "источник": str(ИСТОЧНИК),
        "источник_sha256": hashlib.sha256(ИСТОЧНИК.read_bytes()).hexdigest(),
        "пунктов": len(порядок),
        "порядок": порядок,
        "пункты": пункты,
        "примечание": ("Определение неизменно. Сроки — справочные: ворота по "
                       "времени ничего не решают, владелец следит сам."),
    }
    ОПРЕДЕЛЕНИЕ.write_text(json.dumps(опр, ensure_ascii=False, indent=1) + "\n",
                           encoding="utf-8")

    сост = {"опр_sha256": hashlib.sha256(ОПРЕДЕЛЕНИЕ.read_bytes()).hexdigest(),
            "active": None, "max_active": 1, "пункты": {}, "находки": []}
    for ид in порядок:
        готов = not пункты[ид]["depends"]
        сост["пункты"][ид] = {
            "state": "READY" if готов else "LOCKED",
            "attempts": [], "evidence": [], "done_by": None}
    СОСТОЯНИЕ.write_text(json.dumps(сост, ensure_ascii=False, indent=1) + "\n",
                         encoding="utf-8")
    return опр, сост


def сверка():
    """Определение обратно к источнику. Расхождение — беда, а не мелочь."""
    if not ОПРЕДЕЛЕНИЕ.exists():
        return ["определения нет"]
    опр = json.loads(ОПРЕДЕЛЕНИЕ.read_text(encoding="utf-8"))
    беды = []
    сейчас_sha = hashlib.sha256(ИСТОЧНИК.read_bytes()).hexdigest()
    if опр["источник_sha256"] != сейчас_sha:
        беды.append(f"источник изменился: было {опр['источник_sha256'][:16]}…, "
                    f"стало {сейчас_sha[:16]}…")
    пункты, порядок = разобрать()
    if порядок != опр["порядок"]:
        беды.append(f"порядок пунктов разошёлся: было {len(опр['порядок'])}, "
                    f"стало {len(порядок)}")
    for ид in порядок:
        в_опр = опр["пункты"].get(ид)
        if в_опр is None:
            беды.append(f"{ид}: нет в определении")
            continue
        for поле in ("depends", "risk", "required_evidence", "level", "class"):
            if пункты[ид].get(поле) != в_опр.get(поле):
                беды.append(f"{ид}.{поле}: источник {пункты[ид].get(поле)!r} "
                            f"≠ определение {в_опр.get(поле)!r}")
    return беды


if __name__ == "__main__":
    if "--сверка" in sys.argv:
        б = сверка()
        if б:
            print("РАСХОЖДЕНИЯ:")
            for с in б:
                print("  ", с)
            sys.exit(1)
        print("сверка сошлась: определение отвечает источнику")
        sys.exit(0)
    о, с = собрать()
    готовы = [и for и in о["порядок"] if с["пункты"][и]["state"] == "READY"]
    закрыты = sum(1 for и in о["порядок"] if с["пункты"][и]["state"] == "LOCKED")
    print(f"пунктов: {о['пунктов']}")
    print(f"источник sha256: {о['источник_sha256'][:32]}…")
    print(f"READY: {готовы}   LOCKED: {закрыты}   DONE: 0   ACTIVE: нет")
