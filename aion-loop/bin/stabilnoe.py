#!/usr/bin/env python3
"""Стабильное, основа, точка возврата, изоляция кандидата (N-L2-03, L2.1–L2.3).

Стабильное — не «текущая папка», а явная ссылка: git-метка на коммите канона плюс
отпечаток каждого отслеживаемого файла (state/stable.json). Кандидат — отдельное
рабочее дерево git (каталог рядом с каноном, своя ветка): жёлтый риск → изоляция
каталогом, стабильное дерево не трогается. Точка возврата проверяется ДО изменения:
метка разворачивается в песочницу, отпечатки сверяются с записью.

    python3 bin/stabilnoe.py zafiksirovat      метка stable-<дата>-<n> + state/stable.json (отпечатки)
    python3 bin/stabilnoe.py kandidat          рабочее дерево ../AION-CONTROL-kandidat + state/candidate.json
    python3 bin/stabilnoe.py zamer             отпечатки стабильного и кандидата сейчас (сравнение с записью)
    python3 bin/stabilnoe.py vozvrat           развернуть метку в песочницу и сверить отпечатки (точка возврата)
    python3 bin/stabilnoe.py --proby [--uliki <dir>]   весь порядок: замер → возврат → изменение кандидата → замер
"""
import datetime as dt
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parent.parent
СТАБИЛЬНОЕ = КОРЕНЬ / "state" / "stable.json"
КАНДИДАТ = КОРЕНЬ / "state" / "candidate.json"
ДЕРЕВО_КАНДИДАТА = КОРЕНЬ.parent / "AION-CONTROL-kandidat"


def git(*args, cwd=КОРЕНЬ):
    r = subprocess.run(["git", *args], capture_output=True, text=True, cwd=str(cwd))
    return r.returncode, (r.stdout + r.stderr).strip()


def отпечатки_дерева(дерево: Path, ref="HEAD") -> dict:
    """sha256 содержимого каждого отслеживаемого файла в ref (из git, не с диска)."""
    код, список = git("ls-tree", "-r", "--name-only", ref, cwd=дерево)
    out = {}
    for имя in список.splitlines():
        r = subprocess.run(["git", "show", f"{ref}:{имя}"], capture_output=True, cwd=str(дерево))   # байты: файлы бывают двоичными
        if r.returncode == 0:
            out[имя] = hashlib.sha256(r.stdout).hexdigest()
    return out


def отпечатки_диска(дерево: Path) -> dict:
    код, список = git("ls-files", cwd=дерево)
    out = {}
    for имя in список.splitlines():
        п = дерево / имя
        if п.is_file():
            out[имя] = hashlib.sha256(п.read_bytes()).hexdigest()
    return out


def сводный(отп: dict) -> str:
    return hashlib.sha256("".join(f"{k}:{v}\n" for k, v in sorted(отп.items())).encode()).hexdigest()


def zafiksirovat() -> dict:
    код, коммит = git("rev-parse", "HEAD")
    сегодня = dt.date.today().isoformat()
    код, метки = git("tag", "--list", f"stable-{сегодня}-*")
    n = len(метки.splitlines()) + 1
    метка = f"stable-{сегодня}-{n:02d}"
    git("tag", "-a", метка, "-m", f"STABLE {метка}: явная ссылка на стабильное состояние канона")
    отп = отпечатки_дерева(КОРЕНЬ, метка)
    запись = {"STABLE_ID": метка, "commit": коммит, "tag": метка, "files": len(отп), "manifest_sha256": сводный(отп),
              "manifest": отп, "runtime": f"python {sys.version_info.major}.{sys.version_info.minor}",
              "evidence_set": "checklist/letopis.ndjson DONE до этого коммита", "validator": "sudya (3 голоса) через ворота",
              "promotion_time": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
              "restore_status": "NOT_PROVEN — проверить командой vozvrat"}
    СТАБИЛЬНОЕ.write_text(json.dumps(запись, ensure_ascii=False, indent=1), encoding="utf-8")
    return запись


def kandidat() -> dict:
    ветка = f"kandidat/{dt.date.today().isoformat()}"
    if ДЕРЕВО_КАНДИДАТА.exists():
        git("worktree", "remove", "--force", str(ДЕРЕВО_КАНДИДАТА))
    git("branch", "-D", ветка)
    код, в = git("worktree", "add", "-b", ветка, str(ДЕРЕВО_КАНДИДАТА), "HEAD")
    отп = отпечатки_диска(ДЕРЕВО_КАНДИДАТА)
    запись = {"CANDIDATE_ID": ветка, "worktree": str(ДЕРЕВО_КАНДИДАТА), "branch": ветка,
              "base_commit": git("rev-parse", "HEAD")[1], "isolation": "отдельное рабочее дерево git и ветка; стабильное дерево не затрагивается (жёлтый риск)",
              "manifest_sha256": сводный(отп), "files": len(отп), "created": dt.datetime.now().astimezone().isoformat(timespec="seconds")}
    КАНДИДАТ.write_text(json.dumps(запись, ensure_ascii=False, indent=1), encoding="utf-8")
    return запись


def zamer() -> dict:
    ст = json.loads(СТАБИЛЬНОЕ.read_text(encoding="utf-8"))
    сейчас_ст = отпечатки_дерева(КОРЕНЬ, ст["tag"])
    итог = {"stable": {"ref": ст["tag"], "recorded": ст["manifest_sha256"], "now": сводный(сейчас_ст),
                       "unchanged": сводный(сейчас_ст) == ст["manifest_sha256"]}}
    if КАНДИДАТ.exists() and ДЕРЕВО_КАНДИДАТА.exists():
        к = json.loads(КАНДИДАТ.read_text(encoding="utf-8"))
        сейчас_к = отпечатки_диска(ДЕРЕВО_КАНДИДАТА)
        итог["candidate"] = {"ref": к["branch"], "recorded": к["manifest_sha256"], "now": сводный(сейчас_к),
                             "unchanged": сводный(сейчас_к) == к["manifest_sha256"]}
    return итог


def vozvrat() -> dict:
    """Точка возврата: развернуть метку в песочницу и сверить каждый файл с записью."""
    ст = json.loads(СТАБИЛЬНОЕ.read_text(encoding="utf-8"))
    песочница = Path(tempfile.mkdtemp(prefix="vozvrat-"))
    try:
        код, в = git("worktree", "add", "--detach", str(песочница / "restore"), ст["tag"])
        if код != 0:
            return {"restored": False, "why": в[-200:]}
        отп = отпечатки_диска(песочница / "restore")
        расх = [f for f in set(отп) | set(ст["manifest"]) if отп.get(f) != ст["manifest"].get(f)]
        итог = {"restored": not расх, "tag": ст["tag"], "files_checked": len(отп), "mismatches": расх[:10],
                "manifest_sha256": сводный(отп), "recorded": ст["manifest_sha256"]}
        if not расх:
            ст["restore_status"] = f"PROVEN {dt.datetime.now().astimezone().isoformat(timespec='seconds')}"
            СТАБИЛЬНОЕ.write_text(json.dumps(ст, ensure_ascii=False, indent=1), encoding="utf-8")
        return итог
    finally:
        git("worktree", "remove", "--force", str(песочница / "restore"))
        shutil.rmtree(песочница, ignore_errors=True)


def пробы(улики: Path = None) -> int:
    вывод = []
    def скажи(т=""):
        вывод.append(т); print(т)
    итоги = {}
    ст = zafiksirovat()
    скажи(f"--- 1. стабильное зафиксировано: {ст['STABLE_ID']} @ {ст['commit'][:12]}, файлов {ст['files']}, сводный sha {ст['manifest_sha256'][:16]}…")
    итоги["1. явная ссылка на стабильное (метка + отпечатки)"] = bool(ст["tag"]) and ст["files"] > 0
    к = kandidat()
    скажи(f"--- 2. кандидат: {к['CANDIDATE_ID']} в {к['worktree']}, сводный sha {к['manifest_sha256'][:16]}… ({к['isolation']})")
    итоги["2. отдельный кандидат, изолирован каталогом и веткой"] = ДЕРЕВО_КАНДИДАТА.exists() and к["manifest_sha256"] == ст["manifest_sha256"]
    з0 = zamer()
    скажи(f"--- 3. замер ДО изменения: стабильное {з0['stable']['now'][:16]}… кандидат {з0['candidate']['now'][:16]}…")
    итоги["3. замер стабильного и кандидата до изменения"] = з0["stable"]["unchanged"] and з0["candidate"]["unchanged"]
    в = vozvrat()
    скажи(f"--- 4. возврат ДО изменения: развёрнута метка {в.get('tag')}, файлов сверено {в.get('files_checked')}, расхождений {len(в.get('mismatches', []))} → {'ВОССТАНОВЛЕНИЕ ПОДТВЕРЖДЕНО' if в['restored'] else 'НЕТ'}")
    итоги["4. точка возврата проверена до изменения"] = в["restored"]
    (ДЕРЕВО_КАНДИДАТА / "KANDIDAT-PROBA.md").write_text("# проба N-L2-03: изменение только в кандидате\n", encoding="utf-8")
    git("add", "KANDIDAT-PROBA.md", cwd=ДЕРЕВО_КАНДИДАТА)
    git("-c", "user.name=kandidat", "-c", "user.email=k@l", "commit", "-qm", "kandidat: проба изменения", cwd=ДЕРЕВО_КАНДИДАТА)
    з1 = zamer()
    скажи(f"--- 5. изменение внесено в кандидата: стабильное {з1['stable']['now'][:16]}… ({'не изменилось' if з1['stable']['unchanged'] else 'ИЗМЕНИЛОСЬ'}), кандидат {з1['candidate']['now'][:16]}… ({'изменился' if not з1['candidate']['unchanged'] else 'не изменился'})")
    итоги["5. изменение кандидата не меняет стабильное"] = з1["stable"]["unchanged"] and not з1["candidate"]["unchanged"]
    в2 = vozvrat()
    итоги["6. возврат после изменения кандидата тоже сходится"] = в2["restored"]
    скажи(f"--- 6. возврат после изменения кандидата: {'ПОДТВЕРЖДЁН' if в2['restored'] else 'НЕТ'}")
    скажи("=== ИТОГ ПРОБ ===")
    for имя, ок in итоги.items():
        скажи(f"  {'✓' if ок else '✗'} {имя}")
    всё = all(итоги.values())
    скажи(f"ПРОБ: {sum(итоги.values())} из {len(итоги)} — {'ВСЕ ВЕРНЫ' if всё else 'ЕСТЬ ОШИБКИ'}")
    if улики:
        улики.mkdir(parents=True, exist_ok=True)
        (улики / "vyvod-prob.txt").write_text("\n".join(вывод) + "\n", encoding="utf-8")
        (улики / "sha-do-i-posle.json").write_text(json.dumps({"do": з0, "posle": з1, "vozvrat_do": в, "vozvrat_posle": в2}, ensure_ascii=False, indent=1), encoding="utf-8")
        shutil.copy2(СТАБИЛЬНОЕ, улики / "stable.json"); shutil.copy2(КАНДИДАТ, улики / "candidate.json")
    return 0 if всё else 1


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        print(__doc__); sys.exit(2)
    if a[0] == "--proby":
        d = Path(a[a.index("--uliki") + 1]).resolve() if "--uliki" in a else None
        sys.exit(пробы(d))
    f = {"zafiksirovat": zafiksirovat, "kandidat": kandidat, "zamer": zamer, "vozvrat": vozvrat}.get(a[0])
    if not f:
        print(__doc__); sys.exit(2)
    print(json.dumps({k: v for k, v in f().items() if k != "manifest"}, ensure_ascii=False, indent=1))
