#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "openai-codex>=0.162.1",
#     "pydantic>=2.14.0",
# ]
# ///


"""检查当前 Codex thread 的模型，判断是否推荐快速子代理策略。"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from openai_codex import CodexConfig
from openai_codex.client import CodexClient
from openai_codex.errors import CodexError
from pydantic import BaseModel

MODEL_ALLOWLIST = frozenset({"gpt-6.1-sol"})


class ModelLookupError(RuntimeError):
    """无法可靠识别当前模型。"""


class ThreadInfo(BaseModel):
    """只读 thread 元信息。"""

    id: str
    path: str | None = None


class ThreadResponse(BaseModel):
    """thread/read 的最小返回结构。"""

    thread: ThreadInfo


def read_latest_model(path: Path) -> str:
    """读取最新完整 turn_context，忽略正在写入的末尾残行。"""

    model = None
    try:
        with path.open(encoding="utf-8") as lines:
            for number, line in enumerate(lines, 1):
                if not line.strip():
                    continue
                if not line.endswith("\n"):
                    break
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ModelLookupError(f"rollout 第 {number} 行 JSON 无效") from exc
                if isinstance(item, dict) and item.get("type") == "turn_context":
                    payload = item.get("payload")
                    model = payload.get("model") if isinstance(payload, dict) else None
    except (OSError, UnicodeError) as exc:
        raise ModelLookupError(f"无法读取 rollout：{exc}") from exc
    if not isinstance(model, str) or not model.strip():
        raise ModelLookupError("最新完整 turn_context 缺少模型信息")
    return model.strip()


def resolve_model(thread_id: str) -> str:
    """沿用 repository-workflow 的只读 app-server 探测方式。"""

    codex_bin = os.environ.get("CODEX_BIN", "").strip() or shutil.which("codex")
    if not codex_bin:
        raise ModelLookupError("找不到 Codex；请设置 CODEX_BIN 或检查 PATH")
    config = CodexConfig(
        codex_bin=codex_bin,
        client_name="codex-fast-delegation",
        client_title="Codex Fast Delegation",
        experimental_api=False,
    )
    try:
        with CodexClient(config) as client:
            client.initialize()
            response = client.request(
                "thread/read",
                {"threadId": thread_id, "includeTurns": False},
                response_model=ThreadResponse,
            )
    except (CodexError, OSError, ValueError) as exc:
        raise ModelLookupError(f"读取 Codex thread 失败：{exc}") from exc
    if response.thread.id != thread_id:
        raise ModelLookupError("返回的 thread ID 与当前 thread 不一致")
    if not response.thread.path or not response.thread.path.strip():
        raise ModelLookupError("当前 thread 没有 rollout 路径")
    return read_latest_model(Path(response.thread.path))


def main() -> int:
    """读取 CODEX_THREAD_ID 对应的最新模型；白名单精确匹配，未命中也正常退出。"""

    thread_id = os.environ.get("CODEX_THREAD_ID", "").strip()
    model = None
    failed = False
    try:
        if not thread_id:
            raise ModelLookupError("未设置 CODEX_THREAD_ID")
        model = resolve_model(thread_id)
        recommended = model in MODEL_ALLOWLIST
        reason = "当前模型命中白名单" if recommended else "当前模型不在白名单中"
    except ModelLookupError as exc:
        failed = True
        recommended = False
        reason = str(exc)
    print(f"当前 thread：{thread_id or '未知'}")
    print(f"当前模型：{model or '未知'}")
    print(f"是否推荐快速子代理策略：{'是' if recommended else '否'}")
    print(f"原因：{reason}")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
