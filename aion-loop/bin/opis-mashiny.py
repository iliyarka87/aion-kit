#!/usr/bin/env python3
"""Опись машины для переезда (Air → Mac mini, macOS 27): что установлено, какие службы,
какие пути зашиты, где ключи, какие версии. Только чтение. Секреты не печатаются — только
где они лежат.

    python3 bin/opis-mashiny.py [--uliki <dir>]     → state/opis-mashiny.json + человеческий отчёт
"""
import json
import os
import plistlib
import subprocess
import sys
import datetime as dt
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parent.parent
HOME = Path.home()


def sh(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip()
    except Exception as e:
        return f"?: {e}"


def opis():
    o = {"снято": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "машина": sh("sysctl -n hw.model"),
         "macos": sh("sw_vers -productVersion"), "пользователь": os.environ.get("USER"), "дом": str(HOME)}
    o["инструменты"] = {}
    for имя, cmd in (("python3", "/usr/bin/python3 --version"), ("python3.12 (судья)", str(HOME / ".aion-sudya/venv/bin/python") + " --version"),
                      ("xcode", "xcodebuild -version | head -1"), ("clt", "xcode-select -p"), ("git", "git --version"), ("gh", "gh --version | head -1"),
                      ("claude", "claude --version"), ("codex (app)", "/Applications/ChatGPT.app/Contents/Resources/codex --version"),
                      ("codex (cli)", str(HOME / ".local/bin/codex") + " --version"), ("cloudflared", str(HOME / ".local/bin/cloudflared") + " --version"),
                      ("node", "node --version"), ("tailscale", "/Applications/Tailscale.app/Contents/MacOS/Tailscale version | head -1"),
                      ("docker", "docker --version"), ("inspect_ai", str(HOME / ".aion-sudya/venv/bin/python") + " -c 'import inspect_ai;print(inspect_ai.__version__)'")):
        o["инструменты"][имя] = sh(cmd)[:80]
    o["службы_launchd"] = []
    for f in sorted((HOME / "Library/LaunchAgents").glob("com.aion.*.plist")) + sorted(Path("/Library/LaunchAgents").glob("com.aion.*.plist")):
        try:
            p = plistlib.load(open(f, "rb"))
        except Exception:
            continue
        args = p.get("ProgramArguments") or []
        o["службы_launchd"].append({"label": p.get("Label"), "file": str(f), "program": " ".join(map(str, args))[:160],
                                    "RunAtLoad": p.get("RunAtLoad"), "KeepAlive": bool(p.get("KeepAlive")),
                                    "зашитые_пути": sorted({a for a in args if str(a).startswith("/Users/")})})
    o["процессы_вне_launchd"] = [l.strip()[:140] for l in sh("ps -axo command | grep -E 'Projects/aion|AION-CONTROL|muse-work' | grep -v grep").splitlines()]
    o["репозитории"] = {}
    for имя, путь in (("AION-CONTROL", КОРЕНЬ), ("aion (рация)", HOME / "Desktop/Projects/aion"), ("AION-LAB", HOME / "Desktop/Projects/aion/AION-LAB"), ("aion2 (ION app)", HOME / "Desktop/Projects/aion2")):
        if (путь / ".git").exists():
            o["репозитории"][имя] = {"путь": str(путь), "remote": sh(f"git -C '{путь}' remote get-url origin"),
                                    "незалито": sh(f"git -C '{путь}' rev-list --count @{{u}}..HEAD 2>/dev/null || echo '?'"),
                                    "грязных_файлов": sh(f"git -C '{путь}' status --porcelain | wc -l").strip()}
        else:
            o["репозитории"][имя] = {"путь": str(путь), "git": "нет"}
    o["ключи_и_секреты_где_лежат"] = [str(p) for p in sorted((HOME / ".config/aion").glob("*"))] + [str(HOME / ".aion-control-sync"), "/etc/codex/requirements.toml (root)", "Keychain: подпись Xcode (сертификат разработчика, экспорт .p12)"]
    o["данные_вне_git"] = {
        "память Клода": str(HOME / ".claude/projects/-Users-iliar/memory"), "настройки и крючки Клода": str(HOME / ".claude") + " (settings.json, hooks/ — под замком владельца)",
        "судейское окружение": str(HOME / ".aion-sudya/venv") + " (пересоздать: requirements-sudya.txt)",
        "голосовые модели": [str(HOME / "Library/Application Support/tts"), str(HOME / ".local/voice")],
        "рабочая папка рации": "/private/tmp/claude-502/голос-мост (временная! копии в ~/Backups)",
        "копии": str(HOME / "Backups"),
        "Codex": [str(HOME / ".codex"), "/etc/codex/requirements.toml"],
    }
    o["зашитые_пути_в_коде"] = {}
    for имя, путь in (("AION-CONTROL", КОРЕНЬ / "bin"), ("svyaz", КОРЕНЬ / "svyaz/src"), ("sync", КОРЕНЬ / "sync"), ("checklist", КОРЕНЬ / "checklist")):
        o["зашитые_пути_в_коде"][имя] = int(sh(f"grep -rl '{Path.home()}' '{путь}' 2>/dev/null | wc -l").strip() or 0)
    return o


def отчёт(o):
    s = [f"# ОПИСЬ МАШИНЫ — {o['машина']} · macOS {o['macos']} · {o['пользователь']} · {o['снято']}", ""]
    s.append("## Инструменты и версии")
    for k, v in o["инструменты"].items():
        s.append(f"- {k}: {v}")
    s.append(""); s.append(f"## Службы launchd (com.aion.*): {len(o['службы_launchd'])}")
    for x in o["службы_launchd"]:
        s.append(f"- {x['label']}  RunAtLoad={x['RunAtLoad']} KeepAlive={x['KeepAlive']}  → {x['program']}")
    s.append(""); s.append(f"## Процессы вне launchd (не встанут сами): {len(o['процессы_вне_launchd'])}")
    s += [f"- {p}" for p in o["процессы_вне_launchd"]]
    s.append(""); s.append("## Репозитории")
    for k, v in o["репозитории"].items():
        s.append(f"- {k}: {json.dumps(v, ensure_ascii=False)}")
    s.append(""); s.append("## Ключи и секреты — где лежат (перенести руками владельца)")
    s += [f"- {p}" for p in o["ключи_и_секреты_где_лежат"]]
    s.append(""); s.append("## Данные вне git")
    for k, v in o["данные_вне_git"].items():
        s.append(f"- {k}: {v}")
    s.append(""); s.append("## Зашитые пути домашней папки в коде (файлов) — при другом имени пользователя править")
    for k, v in o["зашитые_пути_в_коде"].items():
        s.append(f"- {k}: {v}")
    return "\n".join(s) + "\n"


if __name__ == "__main__":
    o = opis()
    (КОРЕНЬ / "state" / "opis-mashiny.json").write_text(json.dumps(o, ensure_ascii=False, indent=1), encoding="utf-8")
    текст = отчёт(o)
    (КОРЕНЬ / "state" / "opis-mashiny.md").write_text(текст, encoding="utf-8")
    if "--uliki" in sys.argv:
        d = Path(sys.argv[sys.argv.index("--uliki") + 1]); d.mkdir(parents=True, exist_ok=True)
        (d / "opis-mashiny.md").write_text(текст, encoding="utf-8")
    print(текст)
