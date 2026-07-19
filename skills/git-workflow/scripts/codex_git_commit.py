#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "openai-codex>=0.144.4",
#     "pydantic>=2.13.4",
#     "typer>=0.27.0",
# ]
# [tool.uv]
# prerelease = "allow"
# ///

"""解析当前 Codex shell 环境对应的 agent/model 信息并输出 JSON。"""

from __future__ import annotations

import json
import os
import shutil

from openai_codex import CodexConfig
from openai_codex.client import CodexClient
from openai_codex.errors import CodexError
from pydantic import BaseModel
import typer

AGENT_NAME = "Codex"
app = typer.Typer(add_completion=False, help="输出当前 Codex agent/model 的 JSON。")


class ThreadModelResponse(BaseModel):
    """只解析 thread/resume 中提交信息需要的 model 字段。"""

    model: str | None = None


def require_thread_id() -> str:
    """读取必需的 `CODEX_THREAD_ID` 环境变量。"""

    thread_id = os.environ.get("CODEX_THREAD_ID", "").strip()
    if not thread_id:
        raise RuntimeError("missing required env var: CODEX_THREAD_ID")
    return thread_id


def resolve_codex_bin() -> str:
    """Resolve the host Codex runtime and refuse the SDK-pinned fallback."""

    explicit = os.environ.get("CODEX_BIN", "").strip()
    if explicit:
        return explicit
    resolved = shutil.which("codex")
    if resolved:
        return resolved
    raise RuntimeError(
        "host Codex binary not found: install codex, make sure it is on PATH, "
        "or set CODEX_BIN to the executable path"
    )


def resolve_model_name(thread_id: str) -> str:
    """通过 Codex SDK 解析 thread 当前 model 名。"""

    config = CodexConfig(
        codex_bin=resolve_codex_bin(),
        client_name="codex-git-workflow",
        client_title="Codex Git Workflow",
        experimental_api=False,
    )
    try:
        with CodexClient(config) as client:
            client.initialize()
            response = client.request(
                "thread/resume",
                {"threadId": thread_id},
                response_model=ThreadModelResponse,
            )
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
