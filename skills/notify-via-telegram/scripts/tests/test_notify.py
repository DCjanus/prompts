from __future__ import annotations

import importlib.util
import json
import secrets
import sys
from pathlib import Path

import pytest
import tomllib
from typer.testing import CliRunner

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "notify.py"
SPEC = importlib.util.spec_from_file_location("notify_via_telegram", SCRIPT_PATH)
assert SPEC is not None
notify = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = notify
SPEC.loader.exec_module(notify)


@pytest.fixture(autouse=True)
def clear_codex_context_ids(monkeypatch) -> None:
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.delenv("CODEX_SESSION_ID", raising=False)


def test_config_set_accepts_negative_chat_id(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    chat_id = f"-{secrets.randbelow(9_000_000_000) + 1_000_000_000}"

    result = CliRunner().invoke(
        notify.app,
        [
            "--config",
            str(config_path),
            "config",
            "set",
            "chat-id",
            chat_id,
        ],
    )

    assert result.exit_code == 0, result.output
    with config_path.open("rb") as config_file:
        assert tomllib.load(config_file)["chat_id"] == chat_id


def test_render_notification_blocks_create_clear_visual_hierarchy() -> None:
    notification = notify.Notification(
        status="success",
        title="修复 <Chat ID>",
        summary="A & B",
        verification="157 > 0",
        action="重新执行",
        context="prompts",
    )

    assert notify.render_notification_blocks(notification) == [
        {
            "type": "heading",
            "text": "修复 <Chat ID>",
            "size": 4,
        },
        {
            "type": "blockquote",
            "blocks": [{"type": "paragraph", "text": "A & B"}],
        },
        {
            "type": "paragraph",
            "text": [
                {"type": "marked", "text": "需要你处理"},
                "：重新执行",
            ],
        },
        {
            "type": "footer",
            "text": ["✅ 已完成", " · ", "157 > 0", " · ", "prompts"],
        },
    ]


def test_json_preview_links_subagent_notification_to_root_thread(monkeypatch) -> None:
    root_thread_id = "01a06b36-0123-7850-9299-04b3f86609d8"
    child_thread_id = "01a06b65-a6b1-7672-8959-961d8d130f66"
    monkeypatch.setenv("CODEX_SESSION_ID", root_thread_id)
    monkeypatch.setenv("CODEX_THREAD_ID", child_thread_id)

    result = CliRunner().invoke(
        notify.app,
        [
            "--json",
            "preview",
            "--status",
            "success",
            "--title",
            "任务完成",
            "--summary",
            "已经完成。",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["rich_message"]["blocks"][-1] == {
        "type": "footer",
        "text": [
            "✅ 已完成",
            " · ",
            {
                "type": "url",
                "text": f"codex://threads/{root_thread_id}",
                "url": f"codex://threads/{root_thread_id}",
            },
        ],
    }


def test_plain_preview_links_fork_to_its_new_root_thread(monkeypatch) -> None:
    forked_thread_id = "01a06c1a-a61c-7c84-a701-2b5c2aca2225"
    monkeypatch.setenv("CODEX_SESSION_ID", forked_thread_id)
    monkeypatch.setenv("CODEX_THREAD_ID", forked_thread_id)

    result = CliRunner().invoke(
        notify.app,
        [
            "preview",
            "--status",
            "success",
            "--title",
            "任务完成",
            "--summary",
            "已经完成。",
        ],
    )

    assert result.exit_code == 0, result.output
    assert result.output.endswith(f"codex://threads/{forked_thread_id}\n")


@pytest.mark.parametrize("session_id", [None, "", "not-a-thread-id"])
def test_plain_preview_omits_codex_link_without_valid_session_id(
    monkeypatch, session_id: str | None
) -> None:
    if session_id is None:
        monkeypatch.delenv("CODEX_SESSION_ID", raising=False)
    else:
        monkeypatch.setenv("CODEX_SESSION_ID", session_id)

    result = CliRunner().invoke(
        notify.app,
        [
            "preview",
            "--status",
            "success",
            "--title",
            "任务完成",
            "--summary",
            "已经完成。",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "codex://threads/" not in result.output


def test_send_uses_structured_rich_message_payload(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        notify,
        "complete_config",
        lambda _path: notify.TelegramConfig(
            bot_token="test-token", chat_id="test-chat"
        ),
    )

    def fake_telegram_call(config, method, payload):
        captured.update(config=config, method=method, payload=payload)
        return {"message_id": 42}

    monkeypatch.setattr(notify, "telegram_call", fake_telegram_call)

    result = CliRunner().invoke(
        notify.app,
        [
            "--config",
            str(tmp_path / "config.toml"),
            "--json",
            "send",
            "--status",
            "success",
            "--title",
            "长任务完成",
            "--summary",
            "所有步骤已经完成。",
            "--verification",
            "157 项测试通过",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["method"] == "sendRichMessage"
    assert captured["payload"] == {
        "chat_id": "test-chat",
        "rich_message": {
            "blocks": [
                {
                    "type": "heading",
                    "text": "长任务完成",
                    "size": 4,
                },
                {
                    "type": "blockquote",
                    "blocks": [{"type": "paragraph", "text": "所有步骤已经完成。"}],
                },
                {
                    "type": "footer",
                    "text": ["✅ 已完成", " · ", "157 项测试通过"],
                },
            ]
        },
    }


def test_json_preview_exposes_rich_message_without_config_or_network(
    monkeypatch,
) -> None:
    def unexpected_access(*_args, **_kwargs):
        raise AssertionError("preview must not access config or Telegram")

    monkeypatch.setattr(notify, "complete_config", unexpected_access)
    monkeypatch.setattr(notify, "telegram_call", unexpected_access)

    result = CliRunner().invoke(
        notify.app,
        [
            "--json",
            "preview",
            "--status",
            "action-required",
            "--title",
            "需要确认",
            "--summary",
            "任务已暂停。",
            "--action",
            "选择发布范围",
        ],
    )

    assert result.exit_code == 0, result.output
    assert result.output.endswith("\n")
    assert json.loads(result.output) == {
        "status": "action-required",
        "rich_message": {
            "blocks": [
                {
                    "type": "heading",
                    "text": "需要确认",
                    "size": 4,
                },
                {
                    "type": "blockquote",
                    "blocks": [{"type": "paragraph", "text": "任务已暂停。"}],
                },
                {
                    "type": "paragraph",
                    "text": [
                        {"type": "marked", "text": "需要你处理"},
                        "：选择发布范围",
                    ],
                },
                {"type": "footer", "text": ["⚠️ 等待处理"]},
            ]
        },
    }


def test_preview_does_not_access_telegram(monkeypatch) -> None:
    def unexpected_telegram_call(*_args, **_kwargs):
        raise AssertionError("preview must not access Telegram")

    monkeypatch.setattr(notify, "telegram_call", unexpected_telegram_call)

    result = CliRunner().invoke(
        notify.app,
        [
            "preview",
            "--status",
            "failed",
            "--title",
            "长任务未完成",
            "--summary",
            "构建失败。",
            "--action",
            "检查构建日志",
        ],
    )

    assert result.exit_code == 0, result.output
    assert result.output == (
        "长任务未完成\n\n> 构建失败。\n\n需要你处理：检查构建日志\n\n❌ 未完成\n"
    )
