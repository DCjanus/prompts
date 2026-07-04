#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "openai-codex>=0.1.0b3",
#     "typer>=0.26.8",
# ]
# [tool.uv]
# prerelease = "allow"
# ///

"""解析当前 Codex shell 环境对应的 agent/model 信息并输出 JSON。"""

from __future__ import annotations

import json
import os

from openai_codex import CodexConfig
from openai_codex.client import CodexClient
from openai_codex.errors import CodexError
import typer

AGENT_NAME = "Codex"
app = typer.Typer(add_completion=False, help="输出当前 Codex agent/model 的 JSON。")


def require_thread_id() -> str:
    """读取必需的 `CODEX_THREAD_ID` 环境变量。"""

    thread_id = os.environ.get("CODEX_THREAD_ID", "").strip()
    if not thread_id:
        raise RuntimeError("missing required env var: CODEX_THREAD_ID")
    return thread_id


def resolve_model_name(thread_id: str) -> str:
    """通过 Codex SDK 解析 thread 当前 model 名。"""

    config = CodexConfig(
        client_name="codex-git-workflow",
        client_title="Codex Git Workflow",
        experimental_api=False,
    )
    try:
        with CodexClient(config) as client:
            client.initialize()
            response = client.thread_resume(thread_id)
    except CodexError as exc:
        raise RuntimeError(f"failed to resolve model via Codex SDK: {exc}") from exc
    except OSError as exc:
        reason = exc.strerror or str(exc)
        raise RuntimeError(f"failed to start Codex SDK app-server: {reason}") from exc

    model = str(response.model or "").strip()
    if not model:
        raise RuntimeError(
            f"failed to resolve model_name for CODEX_THREAD_ID={thread_id}"
        )
    return model


@app.command()
def main() -> None:
    """输出当前环境对应的 `agent_name` 与 `model_name`。"""

    try:
        thread_id = require_thread_id()
        model_name = resolve_model_name(thread_id)
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    payload = {
        "agent_name": AGENT_NAME,
        "model_name": model_name,
    }
    typer.echo(json.dumps(payload, ensure_ascii=True))


if __name__ == "__main__":
    app()
