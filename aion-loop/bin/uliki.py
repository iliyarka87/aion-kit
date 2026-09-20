#!/usr/bin/env python3
"""Улики: форма, место, отпечаток (N-L0-09).

Место — папка evidence/. Форма — запись в evidence/index.jsonl: путь, класс по
07 §9, sha256, размер, пункт чек-листа, когда зафиксировано. Отпечаток — sha256,
и подделанный файл его не пройдёт.

    python3 bin/uliki.py sobrat      переписать индекс по файлам на диске
                                     (неизменённые записи сохраняют дату фиксации)
    python3 bin/uliki.py proverit    целостность: OK / MISMATCH / MISSING, код 1 при беде;
                                     файл на диске без записи — предупреждение
    python3 bin/uliki.py sobytiya    события 06 и зачёты ворот без ссылки на
                                     доказательство → предупреждение
    python3 bin/uliki.py --proby     воспроизвести: подделка → MISMATCH, событие
                                     без улики → предупреждение
"""
import datetime as dt
import hashlib
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parent.parent
УЛИКИ = КОРЕНЬ / "evidence"
ИНДЕКС = УЛИКИ / "index.jsonl"
ЛЕТОПИСЬ_06 = КОРЕНЬ / "06-PROGRESS-LEDGER.md"
ЛЕТОПИСЬ_ВОРОТ = КОРЕНЬ / "checklist" / "letopis.ndjson"
КЛАССЫ = ("OWNER_ACCEPTED", "OWNER_ATTESTED", "INDEPENDENT_GPT_VERIFIED", "EVIDENCE_ON_DISK")


def sha256(п: Path) -> str:
    h = hashlib.sha256()
    with п.open("rb") as f:
        for кусок in iter(lambda: f.read(1 << 20), b""):
            h.update(кусок)
    return h.hexdigest()


def читать_индекс(индекс=ИНДЕКС):
    if not индекс.exists():
        return []
    return [json.loads(с) for с in индекс.read_text(encoding="utf-8").splitlines() if с.strip()]


def файлы_улик(улики=УЛИКИ):
    return sorted(п for п in улики.rglob("*") if п.is_file() and п.name != "index.jsonl"
                  and "__pycache__" not in п.parts and not п.name.startswith("."))


def собрать(улики=УЛИКИ, индекс=ИНДЕКС):
    было = {з["путь"]: з for з in читать_индекс(индекс)}
    сейчас = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")
    записи = []
    for п in файлы_улик(улики):
        отн = str(п.relative_to(улики.parent))
        отп = sha256(п)
        старая = было.get(отн)
        пункт = п.relative_to(улики).parts[0] if п.relative_to(улики).parts[0].startswith("N-") else None
        записи.append({
            "путь": отн,
            "класс": (старая or {}).get("класс", "EVIDENCE_ON_DISK"),
            "sha256": отп,
            "байт": п.stat().st_size,
            "пункт": пункт,
            "зафиксировано": старая["зафиксировано"] if старая and старая["sha256"] == отп else сейчас,
        })
    индекс.write_text("".join(json.dumps(з, ensure_ascii=False) + "\n" for з in записи), encoding="utf-8")
    return записи


def проверить(улики=УЛИКИ, индекс=ИНДЕКС, скажи=print) -> int:
    записи = читать_индекс(индекс)
    if not записи:
        скажи("STOP: индекс пуст или отсутствует — сначала sobrat")
        return 1
    беды = 0
    в_индексе = set()
    for з in записи:
        п = улики.parent / з["путь"]
        в_индексе.add(з["путь"])
        if з.get("класс") not in КЛАССЫ:
            скажи(f"  [WARN    ] {з['путь']}: класс «{з.get('класс')}» не из 07 §9")
        if not п.exists():
            скажи(f"  [MISSING ] {з['путь']}")
            беды += 1
            continue
        отп = sha256(п)
        if отп != з["sha256"]:
            скажи(f"  [MISMATCH] {з['путь']}  в индексе {з['sha256'][:12]}…, на диске {отп[:12]}…")
            беды += 1
        else:
            скажи(f"  [OK      ] {з['путь']}  {з['класс']}")
    лишние = [str(п.relative_to(улики.parent)) for п in файлы_улик(улики)
              if str(п.relative_to(улики.parent)) not in в_индексе]
    for л in лишние:
        скажи(f"  [WARN    ] {л}: файл есть, в индексе нет — sobrat")
    скажи(f"ИТОГ: записей {len(записи)}, бед {беды}, не в индексе {len(лишние)} → "
          + ("ЦЕЛОСТНОСТЬ ПОДТВЕРЖДЕНА" if беды == 0 else "ЦЕЛОСТНОСТЬ НАРУШЕНА"))
    return 0 if беды == 0 else 1


def события_06(текст: str):
    """(EVENT_ID, есть ли непустая ссылка на доказательство) по блокам ### E-…"""
    блоки = re.split(r"^### (?=E-)", текст, flags=re.M)[1:]
    for б in блоки:
        ид = б.split()[0]
        m = re.search(r"^[ \t]*EVIDENCE:[ \t]*(.*)$", б, flags=re.M)
        if not m:
            yield ид, False, "нет строки EVIDENCE"
            continue
        хвост = m.group(1).strip()
        # значение может продолжаться на следующих строках с отступом до следующего КЛЮЧА:
        if not хвост:
            после = б[m.end():]
            for с in после.splitlines():
                if re.match(r"^\s*[A-Z_]+:", с):
                    break
                if с.strip():
                    хвост = с.strip()
                    break
        yield ид, bool(хвост), хвост[:60]


def проверить_события(летопись_06=ЛЕТОПИСЬ_06, летопись_ворот=ЛЕТОПИСЬ_ВОРОТ, скажи=print) -> int:
    предупреждений = 0
    всего = 0
    # летописи 06 может не быть (канон без журнала событий) — тогда событий ноль, и это сказано вслух
    текст_06 = летопись_06.read_text(encoding="utf-8") if летопись_06.exists() else ""
    if not текст_06:
        скажи(f"  [нет 06 ] {летопись_06.name} отсутствует — событий для сверки нет")
    for ид, есть, что in события_06(текст_06):
        всего += 1
        if not есть:
            предупреждений += 1
            скажи(f"  [WARN] 06 событие {ид}: без ссылки на доказательство ({что})")
    зачётов = 0
    if летопись_ворот.exists():
        for с in летопись_ворот.read_text(encoding="utf-8").splitlines():
            if not с.strip():
                continue
            з = json.loads(с)
            if з.get("вид") == "DONE":
                зачётов += 1
                if not з.get("evidence"):
                    предупреждений += 1
                    скажи(f"  [WARN] ворота: зачёт {з.get('item')} без улик")
    скажи(f"ИТОГ: событий 06 — {всего}, зачётов ворот — {зачётов}, предупреждений — {предупреждений}")
    return 0


def пробы() -> int:
    вывод = []
    скажи = lambda т="": (вывод.append(т), print(т))
    итоги = {}
    б = Path(tempfile.mkdtemp(prefix="proba-ulik-"))
    try:
        # песочная папка улик с индексом
        у = б / "evidence"
        if УЛИКИ.exists():
            shutil.copytree(УЛИКИ, у, ignore=shutil.ignore_patterns("index.jsonl"))
        else:
            у.mkdir(parents=True)
        и = у / "index.jsonl"
        собрать(у, и)
        скажи("--- проба «чистый индекс»"); итоги["чистый → код 0"] = проверить(у, и, скажи) == 0
        # подделка: дописать байт в первый файл
        первый = файлы_улик(у)[0]
        with первый.open("ab") as f:
            f.write(b"\n<!-- podmena -->\n")
        скажи(f"--- проба «подделан {первый.relative_to(б)}»")
        подделка = []
        код = проверить(у, и, lambda т: (подделка.append(т), скажи(т)))
        итоги["подделка → MISMATCH, код 1"] = код == 1 and any("[MISMATCH]" in т for т in подделка)
        # пропажа: удалить второй файл
        второй = файлы_улик(у)[1]; второй.unlink()
        скажи(f"--- проба «удалён {второй.relative_to(б)}»")
        пропажа = []
        код = проверить(у, и, lambda т: (пропажа.append(т), скажи(т)))
        итоги["пропажа → MISSING, код 1"] = код == 1 and any("[MISSING ]" in т for т in пропажа)
        # события: копия 06 + одно событие без EVIDENCE
        л06 = б / "06.md"
        л06.write_text((ЛЕТОПИСЬ_06.read_text(encoding="utf-8") if ЛЕТОПИСЬ_06.exists() else "# 06 (проба)\n") + "\n### E-PROBA\n\n    EVENT_ID:      E-PROBA\n"
                       "    EVENT_TYPE:    PROBA\n    EVIDENCE:\n    VERIFIED_BY:   никем\n", encoding="utf-8")
        скажи("--- проба «событие E-PROBA без ссылки на доказательство»")
        соб = []
        проверить_события(л06, ЛЕТОПИСЬ_ВОРОТ, lambda т: (соб.append(т), скажи(т)))
        итоги["событие без улики → предупреждение"] = any("E-PROBA" in т and "[WARN]" in т for т in соб)
    finally:
        shutil.rmtree(б, ignore_errors=True)
    скажи("=== ИТОГ ПРОБ ===")
    for имя, ок in итоги.items():
        скажи(f"  {'✓' if ок else '✗'} {имя}")
    всё = all(итоги.values())
    скажи(f"ПРОБ: {sum(итоги.values())} из {len(итоги)} — {'ВСЕ ВЕРНЫ' if всё else 'ЕСТЬ ОШИБКИ'}")
    return 0 if всё else 1


def главное(дов):
    if not дов:
        print(__doc__)
        return 2
    if дов[0] == "sobrat":
        з = собрать()
        print(f"индекс: {ИНДЕКС.relative_to(КОРЕНЬ)} — {len(з)} записей")
        return 0
    if дов[0] == "proverit":
        return проверить()
    if дов[0] == "sobytiya":
        return проверить_события()
    if дов[0] == "--proby":
        return пробы()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(главное(sys.argv[1:]))
