#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "openai-codex>=0.1.0b3",
# ]
# [tool.uv]
# prerelease = "allow"
# ///

"""Set the current Codex thread name through the Codex Python SDK."""

from __future__ import annotations

import argparse
import os
import sys

from openai_codex import CodexConfig
from openai_codex.client import CodexClient
from openai_codex.errors import CodexError


class ThreadNameError(RuntimeError):
    """User-facing error for this script."""


def set_thread_name(thread_id: str, name: str) -> None:
    """Set the thread name through the official Codex SDK."""

    config = CodexConfig(
        client_name="codex-thread-renamer",
        client_title="Codex Thread Renamer",
        experimental_api=False,
    )
    try:
        with CodexClient(config) as client:
            client.initialize()
            client.thread_set_name(thread_id, name)
    except CodexError as exc:
        raise ThreadNameError(f"Codex SDK 调用失败：{exc}") from exc
    except OSError as exc:
        reason = exc.strerror or str(exc)
        raise ThreadNameError(f"无法启动 Codex SDK app-server：{reason}") from exc


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Set the current Codex thread name through the Codex Python SDK.",
    )
    parser.add_argument("name", help="完整 thread 名称，格式建议为 `Project: 标题`。")
    return parser.parse_args(argv)


def current_thread_id() -> str:
    thread_id = os.environ.get("CODEX_THREAD_ID", "").strip()
    if not thread_id:
        raise ThreadNameError(
            "当前环境没有 CODEX_THREAD_ID，无法判断要设置哪个 Codex 会话。"
        )
    return thread_id


def normalized_name(raw_name: str) -> str:
    name = raw_name.strip()
    if not name:
        raise ThreadNameError("thread 名称不能为空。")
    return name


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        thread_id = current_thread_id()
        name = normalized_name(args.name)
        set_thread_name(thread_id, name)
    except ThreadNameError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1

    print(f"已设置当前 Codex 会话名称：{name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
