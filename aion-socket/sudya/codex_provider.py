#!/usr/bin/env python3
"""A model provider that speaks to the Codex running on this machine.

Inspect talks to model providers over their HTTP APIs. Our judge is not a
service with an API key — it is the Codex app already installed here, reached
over a local stdio pipe. This adapter is the whole bridge between the two.

Nothing here touches the network. The app-server is a child process; the
conversation is JSON-RPC over its stdin and stdout.

Why bother at all: the judge we have gives `PASS` on one reading and `FAIL` on
the next for the same evidence. That is variance, not disagreement, and the
cure is not a better prompt — it is several independent readings and a written
rule for combining them. Inspect already implements that (`epochs` plus the
`at_least` reducer, both measured and maintained elsewhere). This file is the
price of using it: one adapter, so their machinery can drive our judge.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from typing import Any

from inspect_ai.model import (
    ChatMessage,
    GenerateConfig,
    ModelAPI,
    ModelOutput,
    modelapi,
)
from inspect_ai.tool import ToolChoice, ToolInfo

CODEX = "/Applications/ChatGPT.app/Contents/Resources/codex"
ROOT = os.environ.get("AION_ROOT", ".")
TIMEOUT = int(os.environ.get("AION_SUDYA_TIMEOUT", "300"))


def ask_codex(prompt: str, timeout: int = TIMEOUT, cwd: str = ROOT) -> str:
    """One read-only Codex turn in a throwaway thread. Blocking, local."""
    proc = subprocess.Popen(
        [CODEX, "app-server", "--listen", "stdio://"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )
    started, counter, chunks = time.time(), [0], []

    def call(method: str, params: dict) -> int:
        counter[0] += 1
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": counter[0],
                                     "method": method, "params": params},
                                    ensure_ascii=False) + "\n")
        proc.stdin.flush()
        return counter[0]

    def until(predicate) -> dict | None:
        while time.time() - started < timeout:
            line = proc.stdout.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if message.get("method") == "item/agentMessage/delta":
                chunks.append((message.get("params") or {}).get("delta", ""))
            if predicate(message):
                return message
        return None

    try:
        rid = call("initialize", {"clientInfo": {"name": "aion-sudya",
                                                 "title": "Judge", "version": "1"}})
        until(lambda m: m.get("id") == rid)
        # A fresh, ephemeral thread every time, on purpose: each reading must be
        # independent. A judge that remembers its last verdict is one judge
        # voting three times.
        rid = call("thread/start", {"cwd": cwd, "sandbox": "read-only",
                                    "approvalPolicy": "never", "ephemeral": True})
        answer = until(lambda m: m.get("id") == rid)
        thread = (((answer or {}).get("result") or {}).get("thread") or {}).get("id")
        if not thread:
            return ""
        call("turn/start", {"threadId": thread,
                            "input": [{"type": "text", "text": prompt}]})
        until(lambda m: str(m.get("method", "")).startswith("turn/completed"))
    finally:
        try:
            proc.stdin.close()
            proc.terminate()
            proc.wait(timeout=8)
        except Exception:
            proc.kill()
    return "".join(chunks).strip()


def as_prompt(messages: list[ChatMessage]) -> str:
    """Flatten a chat into one instruction.

    Codex takes a single turn of text, so roles are spelled out rather than
    dropped: losing the distinction between the rule and the thing being
    judged is how a grader starts grading the wrong text.
    """
    parts = []
    for message in messages:
        content = message.text if hasattr(message, "text") else str(message)
        role = getattr(message, "role", "user")
        if role == "system":
            parts.append("ПРАВИЛА:\n%s" % content)
        elif role == "assistant":
            parts.append("РАНЕЕ ОТВЕЧЕНО:\n%s" % content)
        else:
            parts.append(content)
    return "\n\n".join(p for p in parts if p.strip())


class CodexModelAPI(ModelAPI):
    """Inspect's side of the bridge."""

    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        api_key_vars: list[str] | None = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ) -> None:
        super().__init__(model_name, base_url, api_key, api_key_vars or [], config)
        self.cwd = model_args.get("cwd", ROOT)
        self.timeout = int(model_args.get("timeout", TIMEOUT))

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        # Blocking subprocess work belongs off the event loop, or several
        # concurrent readings would run one after another.
        text = await asyncio.to_thread(
            ask_codex, as_prompt(input), self.timeout, self.cwd
        )
        return ModelOutput.from_content(model=self.model_name, content=text)

    @property
    def name(self) -> str:
        return "codex-local"

    def max_connections(self) -> int:
        # Each reading spawns its own app-server process. Three at a time is
        # what the vote needs; more only buys contention.
        return 3

    def connection_key(self) -> str:
        return "codex-local"


@modelapi(name="codex")
def codex():
    return CodexModelAPI
