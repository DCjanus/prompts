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
from pathlib import Path

import typer
from openai_codex import CodexConfig
from openai_codex.client import CodexClient
from openai_codex.errors import CodexError
from pydantic import BaseModel

AGENT_NAME = "Codex"
app = typer.Typer(add_completion=False, help="输出当前 Codex agent/model 的 JSON。")


class ThreadReadThread(BaseModel):
    """只解析 thread/read 返回的 rollout 路径。"""

    path: str | None = None


class ThreadReadResponse(BaseModel):
    """只解析 thread/read 中提交信息需要的 thread 字段。"""

    thread: ThreadReadThread


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


def read_latest_model_name(rollout_path: Path) -> str:
    """从 rollout 中读取最后一条完整 turn_context 的模型名。"""

    model_name = ""
    try:
        with rollout_path.open(encoding="utf-8") as rollout:
            for line_number, line in enumerate(rollout, start=1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    # 活跃 thread 可能正在追加最后一行，忽略尚未写完的尾部记录。
                    if not line.endswith("\n"):
                        break
                    raise RuntimeError(
                        f"invalid rollout JSON at line {line_number}: {rollout_path}"
                    ) from exc

                if item.get("type") != "turn_context":
                    continue
                payload = item.get("payload")
                if not isinstance(payload, dict):
                    continue
                candidate = payload.get("model")
                if isinstance(candidate, str) and candidate.strip():
                    model_name = candidate.strip()
    except OSError as exc:
        reason = exc.strerror or str(exc)
        raise RuntimeError(
            f"failed to read Codex rollout {rollout_path}: {reason}"
        ) from exc

    if not model_name:
        raise RuntimeError(f"failed to resolve model_name from rollout: {rollout_path}")
    return model_name


def resolve_model_name(thread_id: str) -> str:
    """通过只读 thread 信息解析当前 model 名。"""

    explicit = os.environ.get("CODEX_MODEL_NAME", "").strip()
    if explicit:
        return explicit

    config = CodexConfig(
        codex_bin=resolve_codex_bin(),
        client_name="codex-repository-workflow",
        client_title="Codex Repository Workflow",
        experimental_api=False,
    )
    try:
        with CodexClient(config) as client:
            client.initialize()
            response = client.request(
                "thread/read",
                {"threadId": thread_id, "includeTurns": False},
                response_model=ThreadReadResponse,
            )
    except CodexError as exc:
        raise RuntimeError(f"failed to resolve model via Codex SDK: {exc}") from exc
    except OSError as exc:
        reason = exc.strerror or str(exc)
        raise RuntimeError(f"failed to start Codex SDK app-server: {reason}") from exc

    rollout_path = str(response.thread.path or "").strip()
    if not rollout_path:
        raise RuntimeError(f"thread {thread_id} does not have a rollout path")
    return read_latest_model_name(Path(rollout_path))


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
