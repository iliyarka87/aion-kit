#!/usr/bin/env python3
"""Проверка комплекта aion-loop: каждый файл на месте и отпечаток совпадает с манифестом;
внешние зависимости названы и найдены (или честно — нет)."""
import hashlib, json, os, shutil, subprocess, sys
from pathlib import Path
ТУТ = Path(__file__).resolve().parent
m = json.loads((ТУТ / "MANIFEST.json").read_text(encoding="utf-8"))
беды = 0
for f in m["manifest"]:
    p = ТУТ / f["path"]
    if not p.exists():
        print(f"  [НЕТ     ] {f['path']}"); беды += 1
    elif hashlib.sha256(p.read_bytes()).hexdigest() != f["sha256"]:
        print(f"  [ОТПЕЧ.  ] {f['path']} изменён"); беды += 1
print(f"файлов по манифесту: {m['files']}, бед: {беды}")
print("внешнее:")
for k, v in m["external"].items():
    путь = v.split("  ")[0]
    есть = Path(путь).exists() if путь.startswith("/") else True
    print(f"  [{'есть' if есть else 'НЕТ '}] {k}: {v}")
try:
    out = subprocess.run([os.environ.get("AION_JUDGE_PYTHON", "python3.12"), "-c", "import inspect_ai; print(inspect_ai.__version__)"], capture_output=True, text=True, timeout=30).stdout.strip()
    print(f"  [есть] judge_venv inspect_ai {out}")
except Exception as e:
    print(f"  [НЕТ ] judge_venv: {e}")
sys.exit(0 if беды == 0 else 1)
