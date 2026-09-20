#!/usr/bin/env python3
"""Собрать registries/failures.jsonl — реестр отказов по 17 полям §5 Мастера.

Две прежние кладовые отказов сливаются сюда без потери: каждая исходная
ячейка попадает в одно из 17 полей дословно, а откуда взята запись — в PATH_OR_LOG.

    02-PRE-PHASE-00-FACTS.md, REPORT-14   таблица 7 колонок → 7 полей один в один
    aion/knowledge/происшествия.jsonl     7 полей → FIRST/LAST_SEEN, FAILURE_FAMILY,
                                           REAL_EXAMPLE, CAUSE_IF_PROVEN, PATH_OR_LOG,
                                           PROTECTION_TESTED
    registries/otkazy-novye.jsonl          новые отказы, сразу в 17 полях, дозапись руками

Сигнатуры известных плохих действий (KNOWN_BAD_ACTIONS) и безопасные замены
(SAFE_ALTERNATIVE) для семейств §5 заданы здесь руками — это и есть то, что
проверка `proverka-otkazov.py` сверяет перед действием.

    python3 bin/sobrat-otkazy.py            собрать заново (детерминированно)
    python3 bin/sobrat-otkazy.py --sverka   собранное = тому, что лежит?
"""
import os
import json
import re
import sys
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parent.parent
ФАКТЫ = КОРЕНЬ / "02-PRE-PHASE-00-FACTS.md"
ПРОИСШЕСТВИЯ = Path(os.environ.get("AION_INCIDENTS_SOURCE", КОРЕНЬ / "registries" / "istochniki" / "proisshestviya.jsonl"))
РЕЕСТР = КОРЕНЬ / "registries" / "failures.jsonl"
НОВЫЕ = КОРЕНЬ / "registries" / "otkazy-novye.jsonl"   # дозапись руками: новые отказы после 14.09, уже в 17 полях

ПОЛЯ = ["FAILURE_ID", "FAILURE_FAMILY", "REAL_EXAMPLE", "FIRST_SEEN", "LAST_SEEN",
        "PATH_OR_LOG", "SYMPTOM", "IMPACT", "CAUSE_IF_PROVEN", "CAUSE_IF_UNKNOWN",
        "CURRENT_PROTECTION", "PROTECTION_TESTED", "REGRESSION_GUARD",
        "KNOWN_BAD_ACTIONS", "SAFE_ALTERNATIVE", "WHY_IT_REPEATED", "STATUS"]

# Сигнатура = регулярное выражение по тексту предлагаемого действия (без учёта регистра).
# Совпало — BLOCKED с именем семейства и безопасной заменой.
СИГНАТУРЫ = {
    "CONTEXT_LOSS": (
        [r"по памяти разговора", r"помню,? что", r"из памяти сессии"],
        "читать состояние с диска: aionctl bootstrap / state/current.json, не память разговора"),
    "COMPACTION_DRIFT": (
        [r"поищ[уи] в (сети|интернете)", r"погугл"],
        "сначала aionctl context <задача>: карта на диске, потом сеть"),
    "STALE_STATE": (
        [r"active-spec\.md", r"спек[аи] (не )?прав"],
        "спека правится в том же ходу, что и код; иначе не трогать"),
    "CONFLICTING_DOCUMENTS": (
        [r"обнов(ить|лю) (только|один) (документ|файл)"],
        "aionctl reconcile: 05 = 01 = 06 в одном ходу, иначе публикация закрыта"),
    "FALSE_COMPLETION": (
        [r"(ожил|работает|готово)[^\n]{0,40}без проверк", r"объяв(ить|лю) (готов|сделан)"],
        "проверка тем же путём, каким пользуется владелец: ключ, порт, ответ; потом слово «готово»"),
    "UNVERIFIED_DONE": (
        [r"pgrep -f [^\n]*(мертв|жив)", r"(мертв|умер)[^\n]{0,30}по (имени|списку) процесс"],
        "kto_zhiv.py: паспорт службы (отпечаток файла + pid), не имя процесса"),
    "TASK_SCOPE_EXPANSION": (
        [r"заодно", r"раз уж", r"пока я здесь"],
        "один пункт за раз через ворота (MAX_ACTIVE=1); находка — vorota.py finding"),
    "OVERENGINEERING": (
        [r"нов(ый|ых) документ", r"созда(м|ть) (архитектур|фреймворк)"],
        "сначала один полный круг на живом, документы только по ходу пункта"),
    "ARCHITECTURE_DRIFT": (
        [r"выбрас(ыва|и)ть недосказан", r"изменю (замысел|поведение) без владельца"],
        "сверка с владельцем до правки поведения; его слова — источник"),
    "STABLE_MUTATION": (
        [r"devicectl[^\n]*install", r"(поставлю|установлю) (прямо )?на (его )?телефон"],
        "кандидат → TestFlight по слову «обновление выкатывай», стабильное не трогать"),
    "HALF_IMPLEMENTED_CHANGE": (
        [r"добав(лю|ить) и (потом )?убер"],
        "пакет изменения целиком с точкой возврата; полумеры не заливаются"),
    "UNCOMMITTED_STATE": (
        [r"закоммичу (потом|позже)", r"без коммита"],
        "коммит в конце каждого хода; sync ловит незакоммиченное"),
    "PROCESS_DIES_WITH_SESSION": (
        [r"nohup [^\n]*&\s*$", r"запущу из (сессии|чата)"],
        "служба через launchd с RunAtLoad/KeepAlive; сессия — не хозяин процесса"),
    "HEALTH_FALSE_POSITIVE": (
        [r"процесс (есть|жив)[^\n]{0,20}значит (работает|здоров)"],
        "здоровье = результат (ответ, свежая запись), не наличие процесса"),
    "RETRY_LOOP": (
        [r"повтор(ять|ю) (пока|до) (не )?(получится|ответит)", r"while true[^\n]*(curl|запрос)"],
        "предохранитель: отступление 2-4-8-15 мин и стоп после 5 отказов"),
    "REPEATED_INCIDENT": (
        [r"почин(ю|ить) (ещё раз|снова|опять)"],
        "L2.8: та же семья второй раз — стоп локальным правкам, ROOT_CAUSE задача"),
    "NO_ROLLBACK": (
        [r"без (отката|точки возврата)"],
        "zolotaya-kopiya + отпечаток стабильной сборки до любой заливки"),
    "BACKUP_WITHOUT_RESTORE_TEST": (
        [r"(копия|бекап|backup) (есть|сделан)[^\n]{0,30}(хватит|достаточно)"],
        "копия считается копией только после проверенного восстановления"),
    "MANUAL_RECOVERY_DEPENDENCY": (
        [r"поднять сможет только (ильяр|владелец)"],
        "автоподъём launchd; токены и ключи в ~/.config/aion с правами 600"),
    "UNKNOWN_SIDE_EFFECT": (
        [r"(наверное|скорее всего) (дошло|ничего не сломал)"],
        "довести до доказательства: журнал, код ответа, повтор пробы"),
    "OWNER_WAIT": (
        [r"(подожду|жду) слова владельца[^\n]{0,30}(вместо|не) исследу"],
        "исследовать всё, что не необратимо; спрашивать только двери"),
}


def строки_таблицы():
    """REPORT-14: строки таблицы как есть, 7 колонок."""
    текст = ФАКТЫ.read_text(encoding="utf-8")
    нач = текст.index("## REPORT-14 REAL_FAILURE_TAXONOMY")
    кон = текст.index("## REPORT-15", нач)
    шапка = None
    for строка in текст[нач:кон].splitlines():
        if not строка.startswith("|"):
            continue
        ячейки = [я.strip() for я in строка.strip().strip("|").split("|")]
        if шапка is None:
            шапка = ячейки
            continue
        if set("".join(ячейки)) <= set("-: "):
            continue
        yield dict(zip(шапка, ячейки))


def из_таблицы():
    for н, р in enumerate(строки_таблицы(), 1):
        ид = р["FAILURE_ID"]
        сиг, замена = СИГНАТУРЫ.get(ид, ([], ""))
        yield {
            "FAILURE_ID": ид,
            "FAILURE_FAMILY": ид,
            "REAL_EXAMPLE": р["REAL_EXAMPLE"],
            "FIRST_SEEN": "2026-09-14",
            "LAST_SEEN": "2026-09-14",
            "PATH_OR_LOG": f"{р['PATH / LOG']} · источник: 02-PRE-PHASE-00-FACTS.md REPORT-14 строка {н}",
            "SYMPTOM": р["REAL_EXAMPLE"],
            "IMPACT": "",
            "CAUSE_IF_PROVEN": р["CAUSE"],
            "CAUSE_IF_UNKNOWN": "",
            "CURRENT_PROTECTION": р["PROTECTION"],
            "PROTECTION_TESTED": р["TESTED"],
            "REGRESSION_GUARD": "",
            "KNOWN_BAD_ACTIONS": сиг,
            "SAFE_ALTERNATIVE": замена,
            "WHY_IT_REPEATED": р["WHY_REPEATED"],
            "STATUS": "OPEN",
        }


def из_происшествий():
    if not ПРОИСШЕСТВИЯ.exists():
        return
    n = 0
    for строка in ПРОИСШЕСТВИЯ.read_text(encoding="utf-8").splitlines():
        if not строка.strip():
            continue
        з = json.loads(строка)
        n += 1
        дата = re.sub(r"[^0-9-]", "", (з.get("когда") or "")[:10]) or "неизвестно"
        yield {
            "FAILURE_ID": f"INC-{дата}-{n:02d}",
            "FAILURE_FAMILY": з.get("вид", ""),
            "REAL_EXAMPLE": з.get("что", ""),
            "FIRST_SEEN": з.get("когда", ""),
            "LAST_SEEN": з.get("когда", ""),
            "PATH_OR_LOG": f"источник: aion/knowledge/происшествия.jsonl строка {n}"
                           f" · коммит: {з.get('коммит', '')} · доказано: {з.get('доказано', '')}",
            "SYMPTOM": з.get("что", ""),
            "IMPACT": "",
            "CAUSE_IF_PROVEN": з.get("почему", ""),
            "CAUSE_IF_UNKNOWN": "",
            "CURRENT_PROTECTION": "",
            "PROTECTION_TESTED": з.get("проверка", ""),
            "REGRESSION_GUARD": "",
            "KNOWN_BAD_ACTIONS": [],
            "SAFE_ALTERNATIVE": "",
            "WHY_IT_REPEATED": "",
            "STATUS": "OPEN",
        }


def из_новых():
    if not НОВЫЕ.exists():
        return
    for строка in НОВЫЕ.read_text(encoding="utf-8").splitlines():
        if строка.strip():
            yield json.loads(строка)


def собрать():
    записи = list(из_таблицы()) + list(из_происшествий()) + list(из_новых())
    for з in записи:
        assert list(з.keys()) == ПОЛЯ, з["FAILURE_ID"]
    return "".join(json.dumps(з, ensure_ascii=False) + "\n" for з in записи)


def главное():
    текст = собрать()
    if "--sverka" in sys.argv:
        лежит = РЕЕСТР.read_text(encoding="utf-8") if РЕЕСТР.exists() else ""
        print("сходится" if лежит == текст else "РАСХОЖДЕНИЕ: реестр не равен сборке")
        return 0 if лежит == текст else 1
    РЕЕСТР.parent.mkdir(parents=True, exist_ok=True)
    РЕЕСТР.write_text(текст, encoding="utf-8")
    n = текст.count("\n")
    print(f"собрано: {РЕЕСТР.relative_to(КОРЕНЬ)} — {n} записей по {len(ПОЛЯ)} полям")
    return 0


if __name__ == "__main__":
    sys.exit(главное())
