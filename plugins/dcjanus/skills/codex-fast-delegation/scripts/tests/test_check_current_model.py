"""验证当前模型识别与推荐策略的对外契约。"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

SCRIPT = Path(__file__).parents[1] / "check_current_model.py"
SPEC = importlib.util.spec_from_file_location("check_current_model", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)
runner = CliRunner()


@pytest.mark.parametrize(
    ("model", "recommended"),
    [("gpt-6.1-sol", True), ("gpt-6-luna", False), ("gpt-6.1-sol-preview", False)],
)
def test_reports_model_and_exact_allowlist_match(monkeypatch, model, recommended):
    monkeypatch.setenv("CODEX_THREAD_ID", "current-thread")
    monkeypatch.setattr(module, "resolve_model", lambda _: model)
    result = runner.invoke(module.app, ["--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["thread_id"] == "current-thread"
    assert payload["model"] == model
    assert payload["recommended"] is recommended


def test_missing_thread_disables_strategy_without_lookup(monkeypatch):
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    lookup = MagicMock()
    monkeypatch.setattr(module, "resolve_model", lookup)
    result = runner.invoke(module.app, ["--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["recommended"] is False
    lookup.assert_not_called()


def test_lookup_failure_returns_unknown_and_no_recommendation(monkeypatch):
    monkeypatch.setenv("CODEX_THREAD_ID", "current-thread")
    monkeypatch.setattr(
        module,
        "resolve_model",
        MagicMock(side_effect=module.ModelLookupError("无法读取")),
    )
    result = runner.invoke(module.app, ["--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout) == {
        "thread_id": "current-thread",
        "model": None,
        "recommended": False,
        "reason": "无法读取",
    }


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


def test_help_exposes_output_contract():
    result = runner.invoke(module.app, ["--help"])
    assert result.exit_code == 0
    assert "--json" in result.stdout
    assert "CODEX_THREAD_ID" in result.stdout
