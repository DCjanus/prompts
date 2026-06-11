from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "gsheets_cli.py"


def load_cli_module():
    spec = importlib.util.spec_from_file_location("gsheets_cli", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_credential_paths_use_xdg_config_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cli = load_cli_module()

    assert cli.config_dir() == tmp_path / "google-sheets-cli"
    assert (
        cli.client_secret_path()
        == tmp_path / "google-sheets-cli" / "client_secret.json"
    )
    assert cli.token_path() == tmp_path / "google-sheets-cli" / "token.json"


def test_values_json_must_be_2d_array():
    cli = load_cli_module()

    with pytest.raises(cli.CliError, match="二维 JSON 数组"):
        cli.ensure_2d_values(["not-a-row"], "--values-json")

    assert cli.ensure_2d_values([["ok"]], "--values-json") == [["ok"]]


def test_batch_updates_validate_range_and_values():
    cli = load_cli_module()

    updates = cli.ensure_batch_updates(
        [{"range": "Sheet1!A1", "values": [["DONE"]]}],
        "--updates-json",
    )

    assert updates == [{"range": "Sheet1!A1", "values": [["DONE"]]}]


def test_missing_client_secret_message_is_actionable(tmp_path):
    cli = load_cli_module()
    path = tmp_path / "google-sheets-cli" / "client_secret.json"

    message = cli.missing_client_secret_message(path)

    assert str(path) in message
    assert "Google Cloud Console" in message
    assert "./scripts/gsheets_cli.py auth login" in message
