from __future__ import annotations

import importlib.util
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


@pytest.mark.parametrize(
    ("status", "header"),
    [
        ("success", "✅ <b>Codex · 任务完成</b>"),
        ("failed", "❌ <b>Codex · 任务失败</b>"),
        ("action-required", "⚠️ <b>Codex · 等待你处理</b>"),
    ],
)
def test_render_notification_html_uses_status_header_and_escapes_fields(
    status: str, header: str
) -> None:
    notification = notify.Notification(
        status=status,
        title="修复 <Chat ID>",
        summary="A & B",
        verification="157 > 0",
        action="重新执行",
        context="prompts",
    )

    assert (
        notify.render_notification_html(notification)
        == f"""{header}
<b>修复 &lt;Chat ID&gt;</b>

A &amp; B

🧪 验证：157 &gt; 0
👉 下一步：重新执行
📦 上下文：prompts"""
    )


def test_send_uses_structured_html_payload(monkeypatch, tmp_path: Path) -> None:
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
    assert captured["method"] == "sendMessage"
    assert captured["payload"] == {
        "chat_id": "test-chat",
        "text": """✅ <b>Codex · 任务完成</b>
<b>长任务完成</b>

所有步骤已经完成。

🧪 验证：157 项测试通过""",
        "parse_mode": "HTML",
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
    assert "❌ Codex · 任务失败" in result.output
    assert "👉 下一步：检查构建日志" in result.output
