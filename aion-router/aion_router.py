#!/usr/bin/env python3
"""Durable, fail-closed AION Router for Codex work.

It chooses a route from an explicit task record and may launch Codex CLI only
when the task's permissions permit it. It never starts a background service,
publishes, commits, pushes, or silently substitutes a manually selected model.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Tuple

ROOT = Path(__file__).resolve().parent
DEFAULT_STATE = Path(os.environ.get("AION_ROUTER_STATE", str(Path.home() / ".aion-router")))
LANE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

# Automatic routing is deliberately smaller than the full catalog. Astra is
# available on direct request but is never an automatic response to a failure.
AUTO_ROUTES = {
    "inventory": ("gpt-5.6-luna", "low"),
    "bounded_edit": ("gpt-5.6-luna", "medium"),
    "implementation": ("gpt-5.6-terra", "medium"),
    "multi_file": ("gpt-5.6-terra", "high"),
    "architecture": ("gpt-5.6-sol", "high"),
    "security_review": ("gpt-5.6-sol", "xhigh"),
}
SUPPORTED = {
    "gpt-5.6-luna": {"low", "medium", "high", "xhigh", "max"},
    "gpt-5.6-terra": {"low", "medium", "high", "xhigh", "max", "ultra"},
    "gpt-5.6-sol": {"low", "medium", "high", "xhigh", "max", "ultra"},
    "gpt-6-astra": {"low", "medium", "high", "xhigh", "max", "ultra"},
    "gpt-5.5": {"low", "medium", "high", "xhigh"},
}


class ControllerError(Exception):
    pass


def load_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ControllerError(f"cannot read task: {exc}") from exc


def validate_task(task: Dict[str, Any]) -> None:
    required = ("task_id", "prompt", "family", "verification")
    missing = [field for field in required if not task.get(field)]
    if missing:
        raise ControllerError("missing required fields: " + ", ".join(missing))
    if task["family"] not in AUTO_ROUTES and not task.get("route"):
        raise ControllerError("unknown task family; use a known family or explicit route")
    if task.get("route"):
        route = task["route"]
        if not route.get("model") or not route.get("effort"):
            raise ControllerError("explicit route needs model and effort")
        if route["model"] not in SUPPORTED or route["effort"] not in SUPPORTED[route["model"]]:
            raise ControllerError("unsupported model and effort combination")
    if task.get("write") and not task.get("write_authorized"):
        raise ControllerError("write task requires write_authorized: true")
    if task.get("external_action"):
        raise ControllerError("external actions are not allowed in unattended tasks")


def decide(task: Dict[str, Any]) -> Dict[str, Any]:
    """Produce a route without invoking a model or inspecting prompt content."""
    validate_task(task)
    if task.get("route"):
        model = task["route"]["model"]
        effort = task["route"]["effort"]
        reason = "manual route; controller must preserve it"
        automatic = False
    else:
        model, effort = AUTO_ROUTES[task["family"]]
        reason = f"automatic policy for family={task['family']}"
        automatic = True
    return {
        "task_id": task["task_id"],
        "model": model,
        "effort": effort,
        "automatic": automatic,
        "reason": reason,
        "verification": task["verification"],
        "write": bool(task.get("write")),
        "created_at": int(time.time()),
        "policy_revision": "AION-MODEL-CONTROLLER-1",
    }


def append_event(state_dir: Path, event: Dict[str, Any]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    with (state_dir / "events.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def lane_state_dir(state_dir: Path, lane: str) -> Path:
    """Keep each chat's plans and journal separate."""
    if not LANE_NAME.fullmatch(lane):
        raise ControllerError("lane must use lowercase letters, numbers, _ or -")
    return state_dir / "lanes" / lane


def make_plan(task_path: Path, state_dir: Path) -> Tuple[Dict[str, Any], Path]:
    task = load_json(task_path)
    decision = decide(task)
    plan_id = f"{task['task_id']}-{uuid.uuid4().hex[:8]}"
    plan = {"plan_id": plan_id, "task": task, "decision": decision, "status": "PLANNED"}
    state_dir.mkdir(parents=True, exist_ok=True)
    plan_path = state_dir / f"{plan_id}.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    append_event(state_dir, {"event": "PLANNED", "plan_id": plan_id, "decision": decision})
    return plan, plan_path


def run_plan(plan_path: Path, state_dir: Path) -> int:
    plan = load_json(plan_path)
    if plan.get("status") != "PLANNED":
        raise ControllerError("only a PLANNED task may run")
    task, decision = plan["task"], plan["decision"]
    if task.get("external_action"):
        raise ControllerError("external actions are blocked")
    sandbox = "workspace-write" if decision["write"] else "read-only"
    command = [
        "codex", "exec", "--model", decision["model"],
        "-c", f'model_reasoning_effort="{decision["effort"]}"',
        "--sandbox", sandbox, "--cd", task.get("workspace", os.getcwd()),
        task["prompt"],
    ]
    plan["status"] = "RUNNING"
    plan["command"] = command[:-1] + ["<task prompt>"]
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    append_event(state_dir, {"event": "RUNNING", "plan_id": plan["plan_id"], "decision": decision})
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    output_path = state_dir / f"{plan['plan_id']}.output.txt"
    output_path.write_text(result.stdout, encoding="utf-8")
    plan["status"] = "AWAITING_VERIFICATION" if result.returncode == 0 else "EXECUTION_FAILED"
    plan["exit_code"] = result.returncode
    plan["output"] = str(output_path)
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    append_event(state_dir, {"event": plan["status"], "plan_id": plan["plan_id"], "exit_code": result.returncode})
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="AION Router: durable Codex model routing")
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--lane", default="default", help="independent chat or worker name")
    sub = parser.add_subparsers(dest="command", required=True)
    plan_parser = sub.add_parser("plan", help="validate a task and save an immutable plan")
    plan_parser.add_argument("task", type=Path)
    run_parser = sub.add_parser("run", help="run one saved plan")
    run_parser.add_argument("plan", type=Path)
    args = parser.parse_args()
    try:
        state_dir = lane_state_dir(args.state_dir, args.lane)
        if args.command == "plan":
            plan, path = make_plan(args.task, state_dir)
            print(json.dumps({"plan": str(path), "decision": plan["decision"]}, ensure_ascii=False, indent=2))
            return 0
        return run_plan(args.plan, state_dir)
    except ControllerError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
