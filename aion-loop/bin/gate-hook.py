#!/usr/bin/env python3
"""Крючок PreToolUse для Claude Code: ворота изменения перед каждым действием.

Подключается ТОЛЬКО руками владельца (решение D-06 / P0-09) — одной строкой в
~/.claude/settings.json:

    "hooks": { "PreToolUse": [ { "matcher": "Edit|Write|MultiEdit|Bash",
        "hooks": [ { "type": "command",
                     "command": "python3 <AION_ROOT>/bin/gate-hook.py" } ] } ] }

Что делает: читает описание вызова инструмента со stdin (JSON от Claude Code),
складывает текст действия (инструмент + команда или путь) и зовёт
`aionctl gate "<действие>"`. BLOCKED → печатает причину в stderr и выходит с кодом 2
(Claude Code не даёт инструменту выполниться). ALLOW → код 0.

Честно о цене: ворота делают проверку зеркала и реестра — около 1–2 с на вызов.
Если крючок мешает работать из-за ложного BLOCKED, его снимает владелец той же строкой;
ворота сами никогда не открываются — это их закон.
"""
import json
import subprocess
import sys
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parent.parent


def main() -> int:
    try:
        данные = json.load(sys.stdin)
    except Exception:
        return 0                                   # не смогли прочесть вызов — не наша зона, не мешаем
    инструмент = данные.get("tool_name", "")
    вход = данные.get("tool_input", {}) or {}
    текст = " ".join(str(вход.get(k, "")) for k in ("command", "file_path", "old_string", "new_string") if вход.get(k))
    действие = f"{инструмент}: {текст}".strip()[:4000]
    р = subprocess.run([sys.executable, str(КОРЕНЬ / "bin" / "aionctl"), "gate", действие],
                       capture_output=True, text=True, timeout=60)
    if р.returncode == 0:
        return 0
    строки = [с for с in р.stdout.splitlines() if "[BLOCK]" in с or с.startswith("GATE:")]
    print("ВОРОТА ИЗМЕНЕНИЯ: " + " | ".join(строки)[:800], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
