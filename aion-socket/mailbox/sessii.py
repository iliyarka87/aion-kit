#!/usr/bin/python3
"""ЖИВЫЕ СЕССИИ VS Code — для выбора собеседника в рации (16.09.2026).

владелец 16 сентября: «привяжись к тому разделу VS Code, где хранятся сессии.
Там не хранятся неактуальные и удалённые. Если старых удалённых нет — в Vox
их тоже не будет, даже если сегодня там сидели и сегодня я удалил. И если
появляются новые — в меню Vox тоже появляются».

Источник правды — реестр открытых окон САМОГО VS Code: ~/.claude/sessions/<pid>.json.
Такой файл заводит живое окно и держит, пока живо; там лежат sessionId, cwd и
метка entrypoint=="claude-vscode". Закрыл или удалил сессию в VS Code — окна
больше нет, и в списке её нет. Ничего не помнится и не хранится у нас.

Почему не файлы разговоров (~/.claude/projects/*.jsonl): они остаются лежать
на диске и ПОСЛЕ удаления сессии в VS Code — по ним удалённая сессия выглядела
бы живой. Это была дыра первой версии, найдена и закрыта 16.09.

Опознание живого окна: pid из имени файла жив И его команда — само расширение
anthropic.claude-code (чужой процесс с тем же номером за окно не сойдёт).
Сверять записанное procStart с ps нельзя: в файле оно в другой часовой зоне.

Название — то же, что владелец видит в панели VS Code: запись ai-title в журнале
сессии (aiTitle). Нет её — берём последнюю его реплику, это тоже узнаваемо.

Отдаётся мостом по /sessii. Выбор владельца мост кладёт в файл ВЫБОР, мозг читает
и делает claude -p --resume <id> — говорит именно с выбранным окном (его
памятью). Пустой выбор — быстрый haiku без памяти.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

РЕЕСТР = Path.home() / ".claude" / "sessions"     # <pid>.json — открытые окна VS Code
ПРОЕКТЫ = Path.home() / ".claude" / "projects"    # журналы сессий (только ради названия)
ВЫБОР = Path("/private/tmp/claude-502/голос-мост/vybor-sessii.txt")   # id выбранной
ПРЕДЕЛ_СПИСКА = 6                                  # не перегружать меню


def _команда(pid: int) -> str:
    """Командная строка процесса; пусто — процесса нет."""
    try:
        return subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


def _окно_живо(pid: int) -> bool:
    """Окно живо = процесс жив и это расширение Claude Code в VS Code."""
    return "anthropic.claude-code" in _команда(pid)


def _журнал(sid: str) -> Path | None:
    """Файл разговора сессии — нужен только чтобы достать её название."""
    for p in ПРОЕКТЫ.glob(f"*/{sid}.jsonl"):
        return p
    return None


def _из_хвоста(jsonl: Path, размер: int = 262144) -> str:
    try:
        with jsonl.open("rb") as f:
            f.seek(0, 2)
            всего = f.tell()
            f.seek(max(0, всего - размер))
            return f.read().decode("utf-8", "ignore")
    except Exception:
        return ""


def _название(sid: str, запасное: str) -> str:
    """То же имя, что видно в панели VS Code: последняя запись ai-title."""
    jsonl = _журнал(sid)
    if jsonl is None:
        return запасное
    хвост = _из_хвоста(jsonl)
    имя = ""
    последняя_реплика = ""
    for line in хвост.splitlines():
        if '"ai-title"' in line:
            try:
                имя = json.loads(line).get("aiTitle", "") or имя
            except Exception:
                pass
        elif '"last-prompt"' in line:
            try:
                последняя_реплика = json.loads(line).get("lastPrompt", "") or последняя_реплика
            except Exception:
                pass
    # в хвосте названия не оказалось — поискать по всему журналу (grep быстрый)
    if not имя:
        try:
            r = subprocess.run(["grep", "-o", r'"aiTitle":"[^"]*"', str(jsonl)],
                               capture_output=True, text=True, timeout=20)
            строки = [s for s in r.stdout.splitlines() if s]
            if строки:
                имя = json.loads("{" + строки[-1] + "}").get("aiTitle", "")
        except Exception:
            pass
    итог = (имя or последняя_реплика or запасное).strip()
    return " ".join(итог.split())[:48] or запасное


def _выбор() -> str:
    try:
        return ВЫБОР.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def живые() -> list[dict]:
    """Окна, открытые в VS Code прямо сейчас. Свежие сверху."""
    выбран = _выбор()
    найдены: dict[str, dict] = {}
    try:
        файлы = sorted(РЕЕСТР.glob("*.json"))
    except Exception:
        файлы = []
    for f in файлы:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if d.get("entrypoint") != "claude-vscode" or d.get("kind") != "interactive":
            continue                                   # не окно VS Code
        sid = d.get("sessionId") or ""
        pid = d.get("pid") or 0
        if not sid or not pid or not _окно_живо(int(pid)):
            continue                                   # окно закрыто или удалено
        когда = int((d.get("updatedAt") or d.get("startedAt") or 0) / 1000)
        найдены[sid] = {
            "id": sid,
            "тема": _название(sid, d.get("name") or "сессия"),
            "проект": (d.get("cwd") or "").split("/")[-1] or "/",
            "обновлена": когда,
            "выбрана": sid == выбран,
        }
    список = sorted(найдены.values(), key=lambda с: с["обновлена"], reverse=True)
    return список[:ПРЕДЕЛ_СПИСКА]


if __name__ == "__main__":
    сейчас = time.time()
    for с in живые():
        m = "★" if с["выбрана"] else " "
        мин = int((сейчас - с["обновлена"]) // 60) if с["обновлена"] else -1
        print(f"{m} {с['id'][:8]}  {мин:>5}m  {с['тема']}")
