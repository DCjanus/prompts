"""验证当前模型识别与推荐策略的对外契约。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

SCRIPT = Path(__file__).parents[1] / "check_current_model.py"
SPEC = importlib.util.spec_from_file_location("check_current_model", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


@pytest.mark.parametrize(
    ("model", "recommended"),
    [("gpt-6.1-sol", True), ("gpt-6-luna", False), ("gpt-6.1-sol-preview", False)],
)
def test_reports_model_and_exact_allowlist_match(
    monkeypatch, capsys, model, recommended
):
    monkeypatch.setenv("CODEX_THREAD_ID", "current-thread")
    monkeypatch.setattr(module, "resolve_model", lambda _: model)
    assert module.main() == 0
    output = capsys.readouterr().out
    assert "当前 thread：current-thread" in output
    assert f"当前模型：{model}\n" in output
    assert f"是否推荐快速子代理策略：{'是' if recommended else '否'}" in output


def test_missing_thread_disables_strategy_without_lookup(monkeypatch, capsys):
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    lookup = MagicMock()
    monkeypatch.setattr(module, "resolve_model", lookup)
    assert module.main() == 1
    output = capsys.readouterr().out
    assert "当前模型：未知" in output
    assert "是否推荐快速子代理策略：否" in output
    lookup.assert_not_called()


def test_lookup_failure_returns_unknown_and_no_recommendation(monkeypatch, capsys):
    monkeypatch.setenv("CODEX_THREAD_ID", "current-thread")
    monkeypatch.setattr(
        module,
        "resolve_model",
        MagicMock(side_effect=module.ModelLookupError("无法读取")),
    )
    assert module.main() == 1
    output = capsys.readouterr().out
    assert "当前模型：未知" in output
    assert "是否推荐快速子代理策略：否" in output
    assert "原因：无法读取" in output


def test_latest_turn_wins_and_partial_tail_is_ignored(tmp_path):
    rollout = tmp_path / "rollout.jsonl"
    rollout.write_text(
        '{"type":"turn_context","payload":{"model":"gpt-6.1-sol"}}\n'
        '{"type":"turn_context","payload":{"model":"gpt-6-luna"}}\n'
        '{"type":"turn_context","payload":',
        encoding="utf-8",
    )
    assert module.read_latest_model(rollout) == "gpt-6-luna"


@pytest.mark.parametrize(
    "tail",
    ['{"type":"turn_context","payload":{}}\n', "invalid-json\n"],
)
def test_missing_latest_model_or_corruption_does_not_use_stale_model(tmp_path, tail):
    rollout = tmp_path / "rollout.jsonl"
    rollout.write_text(
        '{"type":"turn_context","payload":{"model":"gpt-6.1-sol"}}\n' + tail,
        encoding="utf-8",
    )
    with pytest.raises(module.ModelLookupError):
        module.read_latest_model(rollout)


def test_uses_current_thread_read_and_explicit_binary(monkeypatch, tmp_path):
    rollout = tmp_path / "rollout.jsonl"
    rollout.write_text(
        '{"type":"turn_context","payload":{"model":"gpt-6.1-sol"}}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_BIN", "/custom/codex")
    client = MagicMock()
    client.__enter__.return_value = client
    client.request.return_value = SimpleNamespace(
        thread=SimpleNamespace(id="current-thread", path=str(rollout))
    )
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(module, "CodexClient", factory)
    assert module.resolve_model("current-thread") == "gpt-6.1-sol"
    assert factory.call_args.args[0].codex_bin == "/custom/codex"
    client.request.assert_called_once_with(
        "thread/read",
        {"threadId": "current-thread", "includeTurns": False},
        response_model=module.ThreadResponse,
    )
    client.request.return_value.thread.id = "other-thread"
    with pytest.raises(module.ModelLookupError, match="不一致"):
        module.resolve_model("current-thread")
