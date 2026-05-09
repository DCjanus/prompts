#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "typer>=0.24.1",
# ]
# ///

"""解析当前 Codex shell 环境对应的 agent/model 信息并输出 JSON。

风险说明：
- 本脚本当前只读取 SQLite `threads.model`，返回的是该 thread 最近一次已持久化的 model。
- 如果在同一个 session 里刚切换 model，但切换后的 thread 状态还没有完成持久化，
  这里读到的仍然可能是切换前的旧 model。
- 因此，这个脚本更适合表达“最近一次已持久化的 model”，而不是“当前执行时绝对最新的 model”。
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import typer

AGENT_NAME = "Codex"
app = typer.Typer(add_completion=False, help="输出当前 Codex agent/model 的 JSON。")


def resolve_codex_home() -> Path:
    """解析 Codex home 目录。"""

    raw = os.environ.get("CODEX_HOME")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".codex").resolve()


def resolve_sqlite_home(codex_home: Path) -> Path:
    """解析 SQLite state DB 所在目录。"""

    raw = os.environ.get("CODEX_SQLITE_HOME")
    if raw:
        return Path(raw).expanduser().resolve()
    return codex_home


def require_thread_id() -> str:
    """读取必需的 `CODEX_THREAD_ID` 环境变量。"""

    thread_id = os.environ.get("CODEX_THREAD_ID", "").strip()
    if not thread_id:
        raise RuntimeError("missing required env var: CODEX_THREAD_ID")
    return thread_id


def state_db_candidates(sqlite_home: Path) -> list[Path]:
    """按版本号从高到低列出可用的 state DB 文件。"""

    candidates: list[tuple[int, Path]] = []
    for path in sqlite_home.glob("state_*.sqlite"):
        suffix = path.stem.removeprefix("state_")
        if suffix.isdigit():
            candidates.append((int(suffix), path))

    candidates.sort(key=lambda item: item[0], reverse=True)
    ordered = [path for _, path in candidates]

    legacy = sqlite_home / "state.sqlite"
    if legacy.is_file():
        ordered.append(legacy)

    return ordered


def model_from_state_db(thread_id: str, sqlite_home: Path) -> str | None:
    """从 Codex SQLite state DB 中读取 thread 对应的 model。"""

    for db_path in state_db_candidates(sqlite_home):
        try:
            connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        except sqlite3.Error:
            continue

        try:
            row = connection.execute(
                "SELECT model FROM threads WHERE id = ? LIMIT 1",
                (thread_id,),
            ).fetchone()
        except sqlite3.Error:
            row = None
        finally:
            connection.close()

        if row and row[0]:
            model = str(row[0]).strip()
            if model:
                return model

    return None


def resolve_model_name(thread_id: str) -> str:
    """从 SQLite state DB 中解析 thread 最近一次已持久化的 model 名。"""

    codex_home = resolve_codex_home()
    sqlite_home = resolve_sqlite_home(codex_home)

    model = model_from_state_db(thread_id, sqlite_home)
    if model:
        return model

    raise RuntimeError(f"failed to resolve model_name for CODEX_THREAD_ID={thread_id}")


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
