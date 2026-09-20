"""ПРЯМАЯ СВЯЗЬ ДИРЕКТОР ↔ ИСПОЛНИТЕЛЬ. Без GitHub, без браузера, без моста.

Директор — Codex. Исполнитель — живое окно Claude в VS Code.
Всё на одной машине, местными средствами.

    python3 svyaz.py komu-claude "текст"     положить Директору задачу в окно Claude
    python3 svyaz.py ot-claude               забрать последний ответ Claude
    python3 svyaz.py okna                    какие окна Claude живы
    python3 svyaz.py krug "текст"            один круг: отдать -> дождаться -> вернуть

Как устроено:
  · в окно Claude кладём через почтовый ящик окна (v_sessiyu) — это тот же
    путь, которым весь день приходили задачи;
  · ответ читаем из журнала того же окна (iz_sessii), начиная с метки,
    поставленной ДО отправки — чтобы не принять старое за новое.

Сети нет ни в одном шаге. Ломаться нечему: нет ни браузера, ни почтальона.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "mailbox"))   # модули почтового ящика окна
import iz_sessii      # noqa: E402
import sessii         # noqa: E402
import v_sessiyu      # noqa: E402

ВЫБОР = Path("/private/tmp/claude-502/голос-мост/vybor-sessii.txt")
ПРЕДЕЛ = 900          # сколько ждать ответа, секунд
ШАГ = 5


def окно() -> str:
    """Куда класть: выбранное владельцем, иначе свежайшее живое."""
    try:
        в = ВЫБОР.read_text(encoding="utf-8").strip()
        if len(в) >= 8:
            return в
    except Exception:
        pass
    живые = sessii.живые()
    return живые[0]["id"] if живые else ""


def место(sid: str) -> int:
    п = iz_sessii.журнал(sid)
    try:
        return п.stat().st_size if п else 0
    except Exception:
        return 0


def речь_после(sid: str, метка: int) -> str:
    """Слова исполнителя, появившиеся ПОСЛЕ метки. Старое не считаем."""
    п = iz_sessii.журнал(sid)
    if not п:
        return ""
    with п.open("r", encoding="utf-8", errors="replace") as ф:
        ф.seek(метка)
        куски = [iz_sessii._речь(с) for с in ф]
    return "\n".join(к for к in куски if к).strip()


def положить(текст: str) -> tuple:
    sid = окно()
    if not sid:
        return False, "", "нет открытого окна Claude"
    м = место(sid)
    if not v_sessiyu.послать(sid, текст):
        return False, sid, "окно не приняло сообщение"
    return True, sid, str(м)


def забрать(sid: str, метка: int, ждать: int = ПРЕДЕЛ) -> str:
    начало = time.time()
    последнее = ""
    while time.time() - начало < ждать:
        т = речь_после(sid, метка)
        if т and т == последнее and len(т) > 40:
            return т                      # перестал расти — значит договорил
        последнее = т
        time.sleep(ШАГ)
    return последнее


def главное(дов):
    if not дов:
        print(__doc__)
        return 2
    к = дов[0]

    if к == "okna":
        for о in sessii.живые():
            print(f"  {о['id']}  {о.get('название', '')[:50]}")
        в = окно()
        print(f"  выбрано: {в or '—'}")
        return 0

    if к == "komu-claude":
        ок, sid, что = положить(дов[1])
        print(f"{'положено' if ок else 'НЕ ПОЛОЖЕНО'}: окно {sid[:8]}  {что}")
        return 0 if ок else 1

    if к == "ot-claude":
        sid = дов[2] if len(дов) > 2 else окно()
        м = int(дов[1]) if len(дов) > 1 and дов[1].isdigit() else 0
        print(речь_после(sid, м) or "(пусто)")
        return 0

    if к == "krug":
        ок, sid, м = положить(дов[1])
        if not ок:
            print(f"НЕ ПОЛОЖЕНО: {м}")
            return 1
        print(f"отдано в окно {sid[:8]}, жду ответа…", file=sys.stderr)
        о = забрать(sid, int(м))
        print(о or "(ответа не дождался)")
        return 0 if о else 1

    print(f"не знаю команды: {к}")
    return 2


if __name__ == "__main__":
    sys.exit(главное(sys.argv[1:]))
