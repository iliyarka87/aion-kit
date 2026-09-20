#!/usr/bin/python3
"""СЛОВА ИЛЬЯРА — ПРЯМО В ВЫБРАННОЕ ЖИВОЕ ОКНО VS Code (16.09.2026).

владелец 16 сентября: «нужно именно чтобы ты, которая мне тут отвечает,
писала в ION Vox. Без лишних прослоек. Захожу в VS Code — и там та же
переписка. Не дублируется, не подменяется, не дописывается — именно оно».

Значит рация не должна иметь отдельного «мозга»: его claude -p был
третьим лицом, которое отвечало вместо окна и жгло токены впустую.
Слова кладутся в почтовый ящик самого окна и появляются в разговоре
обычной строкой — дальше отвечает то самое окно, которым владелец и пишет.

Ящик и ключ берутся из реестра открытых окон (~/.claude/sessions):
  <pid>.json          — sessionId, messagingSocketPath
  <pid>.<хеш>.key     — peerToken
Старый tools/архив/pechat_v_chat.py умел писать только в СВОЮ сессию
(ключ наследовался из окружения). Здесь ключ читается с диска, поэтому
писать можно в любое живое окно — то, что владелец выбрал в настройках Vox.

Протокол взят оттуда же и не выдуман: auth ключом, затем строка user.
"""
from __future__ import annotations

import json
import os
import socket
from pathlib import Path

РЕЕСТР = Path.home() / ".claude" / "sessions"


def _окно(sid: str) -> tuple:
    """(ящик, ключ) выбранного окна; пустые — окна нет или ключ не читается."""
    for j in РЕЕСТР.glob("*.json"):
        try:
            d = json.loads(j.read_text(encoding="utf-8"))
        except Exception:
            continue
        if d.get("sessionId") != sid:
            continue
        ящик = d.get("messagingSocketPath") or ""
        if not ящик or not os.path.exists(ящик):
            return "", ""
        for k in РЕЕСТР.glob(f"{d.get('pid')}.*.key"):
            try:
                ключ = json.loads(k.read_text(encoding="utf-8")).get("peerToken") or ""
            except Exception:
                ключ = ""
            if ключ:
                return ящик, ключ
        return "", ""
    return "", ""


def послать(sid: str, текст: str) -> bool:
    """Одну фразу владельца в живое окно. True — окно её приняло."""
    текст = (текст or "").strip()
    if not текст or not sid:
        return False
    ящик, ключ = _окно(sid)
    if not ящик or not ключ:
        return False
    try:
        с = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        с.settimeout(10)
        с.connect(ящик)
        с.sendall((json.dumps({"type": "auth", "token": ключ}) + "\n").encode())
        с.sendall((json.dumps({"type": "user",
                               "message": {"role": "user", "content": текст}},
                              ensure_ascii=False) + "\n").encode())
        с.shutdown(socket.SHUT_WR)
        с.close()
        return True
    except Exception:
        return False


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("как звать: v_sessiyu.py <session-id> <текст>")
        raise SystemExit(2)
    print("дошло" if послать(sys.argv[1], " ".join(sys.argv[2:])) else "не дошло")
