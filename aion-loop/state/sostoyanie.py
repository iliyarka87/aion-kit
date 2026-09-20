"""МАШИННОЕ ТЕКУЩЕЕ СОСТОЯНИЕ — слепок 05 по полям Мастера L0.5.

Закон INV-STATE-001: второго источника правды нет. 05-CURRENT-STATE.md —
человеческое зеркало, отсюда всё и берётся. Чего в 05 нет — стоит null и
имя поля в needs_measurement. Ничего не придумывается и не сводится молча.

Один разборщик на оба дела:
    python3 sostoyanie.py --sobrat     собрать current.json из 05
    python3 sostoyanie.py --proverit   заново разобрать 05 и сверить с current.json;
                                       любое расхождение -> код 1, публикация закрыта
"""
import hashlib
import json
import re
import sys
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parent.parent
ПЯТЬ = КОРЕНЬ / "05-CURRENT-STATE.md"
СВОЁ = Path(__file__).parent
ТЕКУЩЕЕ = СВОЁ / "current.json"
СХЕМА = СВОЁ / "schema.json"

SCHEMA_VERSION = "1"

# 17 полей Мастера L0.5 — ровно они, в этом порядке
ПОЛЯ = ["schema_version", "current_phase", "current_product", "current_goal",
        "current_change", "current_task", "last_completed_task",
        "next_authorized_step", "stable_reference", "candidate_reference",
        "dirty_state", "last_test", "last_test_result", "blockers",
        "owner_decisions", "last_checkpoint", "state_status"]

# Откуда в 05 берётся каждое поле. Нет строки — поле не заполняется.
ИЗ_КЛЮЧА = {
    "current_phase": "CURRENT_PHASE",
    "current_product": "CURRENT_PRODUCT",
    "current_change": "CURRENT_CHANGE",
    "current_task": "CURRENT_TASK",
    "last_completed_task": "LAST_VERIFIED_PASS",   # последний ВЕРИФИЦИРОВАННЫЙ PASS
    "last_checkpoint": "LAST_EVENT_ID",
    "state_status": "STATUS",                       # статус самого документа 05
}
ИЗ_РАЗДЕЛА = {
    "blockers": ("CURRENT_BLOCKERS", r"^\s{4}(B-\d+\s.+)$"),
    "owner_decisions": ("OPEN_DECISIONS", r"^\s{4}(D-\d+\s.+)$"),
}


def ключ(текст, имя):
    """Первая строка вида `ИМЯ = значение` (в шапке или с отступом)."""
    м = re.search(rf"^\s*{re.escape(имя)}\s*=\s*(.+?)\s*$", текст, flags=re.M)
    return м.group(1) if м else None


def раздел(текст, заголовок):
    м = re.search(rf"^## {re.escape(заголовок)}.*?$(.*?)(?=^## |\Z)", текст,
                  flags=re.M | re.S)
    return м.group(1) if м else ""


def разобрать():
    т = ПЯТЬ.read_text(encoding="utf-8")
    с = {"schema_version": SCHEMA_VERSION}
    нет = []
    for поле in ПОЛЯ[1:]:
        if поле in ИЗ_КЛЮЧА:
            з = ключ(т, ИЗ_КЛЮЧА[поле])
        elif поле in ИЗ_РАЗДЕЛА:
            заг, обр = ИЗ_РАЗДЕЛА[поле]
            з = re.findall(обр, раздел(т, заг), flags=re.M) or None
        elif поле == "next_authorized_step":
            р = раздел(т, "NEXT_AUTHORIZED_STEP").strip().splitlines()
            з = р[0].strip() if р else None
        else:
            з = None                 # в 05 такого поля нет
        с[поле] = з
        if з is None:
            нет.append(поле)
    с["needs_measurement"] = нет
    с["source"] = {
        "file": "05-CURRENT-STATE.md",
        "sha256": hashlib.sha256(ПЯТЬ.read_bytes()).hexdigest(),
        "updated_at": ключ(т, "UPDATED_AT"),
        "mapping": {**ИЗ_КЛЮЧА,
                    **{k: f"раздел {v[0]}" for k, v in ИЗ_РАЗДЕЛА.items()},
                    "next_authorized_step": "раздел NEXT_AUTHORIZED_STEP, первая строка"},
    }
    return с


def схема():
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "AION machine current state (Master L0.5)",
        "type": "object",
        "additionalProperties": False,
        "required": ПОЛЯ + ["needs_measurement", "source"],
        "properties": {
            **{п: {"type": ["string", "null"]} for п in ПОЛЯ
               if п not in ("blockers", "owner_decisions", "schema_version")},
            "schema_version": {"type": "string", "const": SCHEMA_VERSION},
            "blockers": {"type": ["array", "null"], "items": {"type": "string"}},
            "owner_decisions": {"type": ["array", "null"], "items": {"type": "string"}},
            "needs_measurement": {"type": "array", "items": {"type": "string"}},
            "source": {"type": "object",
                       "required": ["file", "sha256", "updated_at", "mapping"]},
        },
    }


def по_схеме(с, сх):
    """Малый проверщик: обязательные поля, лишние поля, типы, const."""
    беды = []
    for п in сх["required"]:
        if п not in с:
            беды.append(f"нет обязательного поля {п}")
    for п in с:
        if п not in сх["properties"]:
            беды.append(f"лишнее поле {п}")
    ТИП = {"string": str, "null": type(None), "array": list, "object": dict}
    for п, пр in сх["properties"].items():
        if п not in с:
            continue
        типы = пр["type"] if isinstance(пр["type"], list) else [пр["type"]]
        if not any(isinstance(с[п], ТИП[т]) for т in типы):
            беды.append(f"{п}: тип {type(с[п]).__name__}, ждали {типы}")
        if "const" in пр and с[п] != пр["const"]:
            беды.append(f"{п}: {с[п]!r} ≠ {пр['const']!r}")
        if "items" in пр and isinstance(с[п], list):
            for i, э in enumerate(с[п]):
                if not isinstance(э, str):
                    беды.append(f"{п}[{i}]: не строка")
    return беды


def собрать():
    с = разобрать()
    ТЕКУЩЕЕ.write_text(json.dumps(с, ensure_ascii=False, indent=1) + "\n",
                       encoding="utf-8")
    СХЕМА.write_text(json.dumps(схема(), ensure_ascii=False, indent=1) + "\n",
                     encoding="utf-8")
    return с


def проверить():
    беды = []
    if not ТЕКУЩЕЕ.exists():
        return ["current.json нет"]
    тек = json.loads(ТЕКУЩЕЕ.read_text(encoding="utf-8"))
    сх = json.loads(СХЕМА.read_text(encoding="utf-8")) if СХЕМА.exists() else схема()
    беды += [f"схема: {б}" for б in по_схеме(тек, сх)]
    свежее = разобрать()
    for п in ПОЛЯ + ["needs_measurement"]:
        if тек.get(п) != свежее.get(п):
            беды.append(f"{п}: в json {тек.get(п)!r} ≠ в 05 {свежее.get(п)!r}")
    if тек.get("source", {}).get("sha256") != свежее["source"]["sha256"]:
        беды.append("05 изменился после сборки json (sha256 разошёлся)")
    return беды


if __name__ == "__main__":
    if "--sobrat" in sys.argv:
        с = собрать()
        print(f"собрано: {ТЕКУЩЕЕ.name}, {СХЕМА.name}")
        print(f"полей заполнено из 05: {sum(1 for п in ПОЛЯ if с[п] is not None)} из {len(ПОЛЯ)}")
        print(f"needs_measurement: {с['needs_measurement']}")
        sys.exit(0)
    if "--proverit" in sys.argv:
        б = проверить()
        if б:
            print("РАСХОЖДЕНИЕ — ПУБЛИКАЦИЯ ЗАКРЫТА:")
            for с_ in б:
                print("  ", с_)
            sys.exit(1)
        print("сверка сошлась: current.json = 05, схема соблюдена")
        sys.exit(0)
    print(__doc__)
    sys.exit(2)
