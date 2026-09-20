#!/usr/bin/python3
"""ОТВЕТ ИЗ ЖИВОГО ОКНА — обратная дорога рации (16.09.2026).

владелец 16 сентября: «чтобы именно ты, которая мне тут отвечает, писала
в Vox. Не дублируется, не подменяется, не дописывается — именно оно».

Поэтому ответ не сочиняется заново и ничего в окно не подсаживается:
мы ЧИТАЕМ журнал выбранного окна и берём оттуда мой обычный ответ —
тот самый, который владелец видит в VS Code. Один ответ, два экрана.

Берём только куски типа "text": мысли (thinking) и работа инструментов
(tool_use) вслух не идут — это шум, а не речь.

ВАЖНО про место чтения. При первом взгляде на окно (и при каждой смене
выбранного окна) встаём в КОНЕЦ журнала. Иначе рация вывалит владельцу
всю прошлую переписку разом — сотни ответов подряд.

Старый tools/архив/golos_v_sessiyu.py делал так же: «выход — журнал этой
же сессии читаем и озвучиваем в телефон (только чтение)».
"""
from __future__ import annotations

import json
from pathlib import Path

ПРОЕКТЫ = Path.home() / ".claude" / "projects"


def журнал(sid: str):
    """Файл разговора выбранного окна; None — окна с таким id нет."""
    for p in ПРОЕКТЫ.glob(f"*/{sid}.jsonl"):
        return p
    return None


def _речь(строка: str) -> str:
    """Чистый текст ответа из записи журнала; пусто — это не речь."""
    try:
        d = json.loads(строка)
    except Exception:
        return ""
    if d.get("type") != "assistant":
        return ""
    c = d.get("message", {}).get("content")
    if not isinstance(c, list):
        return ""
    куски = [x.get("text", "") for x in c
             if isinstance(x, dict) and x.get("type") == "text"]
    return "\n".join(к for к in куски if к).strip()


class Слушатель:
    """Следит за журналом выбранного окна и отдаёт только НОВЫЕ ответы."""

    def __init__(self) -> None:
        self.сессия = ""
        self.место = 0

    def _встать_в_конец(self, путь: Path) -> None:
        try:
            self.место = путь.stat().st_size
        except Exception:
            self.место = 0

    def новое(self, sid: str) -> list:
        """Свежие ответы окна sid. Смена окна — молча встаём в его конец."""
        if not sid:
            self.сессия = ""
            return []
        путь = журнал(sid)
        if путь is None:
            return []
        if sid != self.сессия:               # окно сменили — прошлое не читаем
            self.сессия = sid
            self._встать_в_конец(путь)
            return []
        try:
            размер = путь.stat().st_size
        except Exception:
            return []
        if размер < self.место:              # журнал обрезали
            self.место = 0
        if размер <= self.место:
            return []
        try:
            with путь.open("r", encoding="utf-8", errors="ignore") as ф:
                ф.seek(self.место)
                свежее = ф.read()
                self.место = ф.tell()
        except Exception:
            return []
        ответы = []
        for строка in свежее.splitlines():
            текст = _речь(строка)
            if текст:
                ответы.append(текст)
        return ответы


if __name__ == "__main__":
    import sys, time
    if len(sys.argv) < 2:
        print("как звать: iz_sessii.py <session-id>")
        raise SystemExit(2)
    с = Слушатель()
    с.новое(sys.argv[1])
    print("встал в конец журнала, жду новый ответ окна…")
    while True:
        for о in с.новое(sys.argv[1]):
            print("—", " ".join(о.split())[:120])
        time.sleep(0.5)
