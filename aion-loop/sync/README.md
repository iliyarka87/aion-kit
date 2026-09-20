# AION Control Sync — V1

Закон: **NO CRITICAL WORKFLOW STEP MAY DEPEND ON CLAUDE REMEMBERING TO PERFORM IT.**

Что здесь:

| файл | роль |
|---|---|
| `launchd-runner.py` | точка входа для launchd: python3 → bash-скрипт (TCC: `/bin/bash` из launchd в Desktop не пускают, python3 — пускают) |
| `aion-control-sync.sh` | сам механизм: validate → secret scan → PRIVATE check → stage → commit → push (retry 0/10/30/60 с) → remote SHA verify → log |
| `com.aion.control-sync.plist` | описание службы launchd (WatchPaths на папку и 8 файлов + каждые 300 с + при входе/загрузке) |
| `install-launchd.sh` | установка/перезагрузка службы — **запускает владелец** (одна команда) |
| `uninstall-launchd.sh` | снятие службы |

Состояние и журнал — ВНЕ репозитория, в `~/.aion-control-sync/` (иначе WatchPaths ловил свои же записи и служба крутилась каждые 30 с):

- `~/.aion-control-sync/sync.log` — одна строка на запуск: время, trigger, RESULT, SHA (холостые запуски без изменений не пишутся)
- `~/.aion-control-sync/state.json` — последний результат, `remote_match`, `consecutive_failures`, `last_pass_at`, `last_remote_check_epoch`
- `~/.aion-control-sync/push.err` — вывод неудачных push
- `.sync/launchd.out.log` / `launchd.err.log` — stdout/stderr службы

Результаты: `PASS` · `NOOP` (нечего слать) · `VALIDATION_FAILED` (нет файла;
`LAST_EVENT_ID` в 05 ≠ последний `E-xxxx` в 06; `MASTER_VERSION` 05 ≠ `VERSION` 01) ·
`SECRET_BLOCKER` (печатает только путь и тип) · `VISIBILITY_NOT_PRIVATE` (unknown = not private,
push не делается) · `PUSH_FAILED` · `REMOTE_MISMATCH` · `LOCKED` · `TOOLING_MISSING`.
Ни один FAIL не притворяется PASS; `consecutive_failures` растёт, пока не будет PASS/NOOP.

Установка / переустановка после любой правки plist (владелец, в Терминале):

    bash <AION_ROOT>/sync/install-launchd.sh

Проверка, что работает без Клода: изменить `SYNC-PROBE.md`, ничего руками не коммитить,
через ≤5 минут сравнить `git rev-parse HEAD` и `git ls-remote origin main` — должны совпасть,
а в `~/.aion-control-sync/sync.log` появиться строка `trigger=launchd … RESULT=PASS`.

Честные границы V1: служба user-level; Claude Worker технически может править скрипт и plist
(WORKER_TAMPER_PROTECTION = NOT_PROVEN, ROOT_PROTECTED_SYNC = NOT_IMPLEMENTED) — это отдельная
security-задача PHASE-00.
