#!/usr/bin/env python3
"""Ночная копия с проверенным восстановлением (план «Закрепить» п.10; закрывает
BACKUP_WITHOUT_RESTORE_TEST). Копия считается копией только после того, как её
развернули в песочницу и сверили отпечаток каждого файла.

Что копируется (всё, что не восстановить из GitHub одной командой):
    AION-CONTROL            канон целиком (вкл. реестры, улики, состояние, .git)
    AION-LAB                лаборатория (журнал, продукты)
    ~/.config/aion          ключи и настройки служб (права 600 сохраняются)
    ~/.claude/projects/-Users-iliar/memory   память Клода
    ~/.aion-control-sync    состояние публикации
    /private/tmp/claude-502/голос-мост       рабочая папка рации (временная)
Не копируется: рация Projects/aion и aion2 (владелец решает, OD-010), чаты, симуляторы.

    python3 bin/kopiya.py                      сделать копию + восстановить в песочницу + сверить
    python3 bin/kopiya.py --kuda <dir>         куда класть (по умолчанию ~/Backups/nightly)
    python3 bin/kopiya.py --proverit <tar.gz>  только проверить существующую копию
Журнал: ~/Backups/nightly/kopii.ndjson — время, размер, файлов, сверено, итог. Хранится 7 последних.
"""
import datetime as dt
import hashlib
import json
import os
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

HOME = Path.home()
ИСТОЧНИКИ = [HOME / "AION-CONTROL", HOME / "Desktop/Projects/aion/AION-LAB", HOME / ".config/aion",
             HOME / ".claude/projects/-Users-iliar/memory", HOME / ".aion-control-sync", Path("/private/tmp/claude-502/голос-мост")]
КУДА = HOME / "Backups" / "nightly"
ХРАНИТЬ = 7
ИСКЛЮЧИТЬ = ("__pycache__", ".DS_Store", "AION-CONTROL-kandidat")


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def файлы(корень: Path):
    for p in корень.rglob("*"):
        if p.is_file() and not any(x in p.parts for x in ИСКЛЮЧИТЬ) and not p.is_symlink():
            yield p


def сделать(куда: Path) -> dict:
    куда.mkdir(parents=True, exist_ok=True)
    метка = dt.datetime.now().strftime("%Y-%m-%d-%H%M")
    архив = куда / f"aion-{метка}.tar.gz"
    манифест = {}
    with tarfile.open(архив, "w:gz") as tar:
        for src in ИСТОЧНИКИ:
            if not src.exists():
                continue
            имя = str(src).replace("/", "_").strip("_")
            for f in файлы(src):
                rel = f.relative_to(src)
                arc = f"{имя}/{rel}"
                tar.add(f, arcname=arc, recursive=False)
                манифест[arc] = sha(f)
    (куда / f"aion-{метка}.manifest.json").write_text(json.dumps(манифест, ensure_ascii=False), encoding="utf-8")
    return {"archive": str(архив), "manifest": str(куда / f"aion-{метка}.manifest.json"), "files": len(манифест), "bytes": архив.stat().st_size}


def проверить(архив: Path) -> dict:
    """Восстановить в песочницу и сверить каждый файл с манифестом — это и есть доказательство копии."""
    манифест = json.loads(Path(str(архив).replace(".tar.gz", ".manifest.json")).read_text(encoding="utf-8"))
    песочница = Path(tempfile.mkdtemp(prefix="vosstanovlenie-"))
    try:
        with tarfile.open(архив, "r:gz") as tar:
            tar.extractall(песочница)
        расх = []
        for arc, отп in манифест.items():
            p = песочница / arc
            if not p.exists() or sha(p) != отп:
                расх.append(arc)
        return {"restored": not расх, "checked": len(манифест), "mismatches": расх[:10]}
    finally:
        shutil.rmtree(песочница, ignore_errors=True)


def подрезать(куда: Path):
    архивы = sorted(куда.glob("aion-*.tar.gz"))
    for старый in архивы[:-ХРАНИТЬ]:
        старый.unlink(missing_ok=True)
        Path(str(старый).replace(".tar.gz", ".manifest.json")).unlink(missing_ok=True)


def main(argv):
    куда = Path(argv[argv.index("--kuda") + 1]) if "--kuda" in argv else КУДА
    if "--proverit" in argv:
        r = проверить(Path(argv[argv.index("--proverit") + 1]))
        print(json.dumps(r, ensure_ascii=False)); return 0 if r["restored"] else 1
    t0 = dt.datetime.now()
    к = сделать(куда)
    в = проверить(Path(к["archive"]))
    подрезать(куда)
    запись = {"t": t0.astimezone().isoformat(timespec="seconds"), "archive": к["archive"], "files": к["files"], "mb": round(к["bytes"] / 1048576, 1),
              "restore_checked": в["checked"], "restored": в["restored"], "mismatches": в["mismatches"],
              "seconds": round((dt.datetime.now() - t0).total_seconds(), 1), "result": "PASS" if в["restored"] else "FAIL"}
    with (куда / "kopii.ndjson").open("a", encoding="utf-8") as h:
        h.write(json.dumps(запись, ensure_ascii=False) + "\n")
    print(f"копия: {к['archive']}  {запись['mb']} МБ, файлов {к['files']}")
    print(f"восстановление в песочницу: сверено {в['checked']}, расхождений {len(в['mismatches'])} → {'ВОССТАНОВЛЕНИЕ ПОДТВЕРЖДЕНО' if в['restored'] else 'НЕ ПОДТВЕРЖДЕНО'}  ({запись['seconds']} с)")
    return 0 if в["restored"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
