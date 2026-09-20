#!/usr/bin/python3
"""AION Control Sync — launchd entry point.

Why this exists: macOS TCC forbids /bin/bash spawned by launchd from touching
~/Desktop ("Operation not permitted", observed 2026-09-14 18:15 EDT), while
/usr/bin/python3 already holds Desktop access (all other com.aion.* agents run
through it). A child process inherits the TCC responsibility of the process
launchd started, so python3 → bash → git/gh works.

Runs the deterministic sync script and propagates its exit code. No logic here.
"""
import os
import subprocess
import sys

SCRIPT = os.path.join(os.environ.get("AION_CONTROL_DIR", "<AION_ROOT>"), "sync", "aion-control-sync.sh")
TRIGGER = sys.argv[1] if len(sys.argv) > 1 else "launchd"

os.environ.setdefault("HOME", os.path.expanduser("~"))
os.environ["PATH"] = os.path.expanduser("~/.local/bin") + ":/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

try:
    rc = subprocess.run(["/bin/bash", SCRIPT, TRIGGER], cwd=os.environ.get("AION_CONTROL_DIR", "<AION_ROOT>")).returncode
except Exception as exc:  # noqa: BLE001 — surface the failure, never hide it
    sys.stderr.write(f"launchd-runner: cannot start sync script: {exc}\n")
    rc = 8
sys.exit(rc)
