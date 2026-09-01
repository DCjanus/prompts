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


def test_values_json_cells_must_be_scalars():
    cli = load_cli_module()

    with pytest.raises(cli.CliError, match=r"\[0\]\[1\].*JSON 对象或数组"):
        cli.ensure_2d_values([["ok", {"$date": "2026-09-01"}]], "--values-json")


def test_spreadsheet_create_body_uses_grid_properties_for_frozen_rows():
    cli = load_cli_module()

    body = cli.spreadsheet_create_body(" Audit ", ["Issues", "Notes"], 1)

    assert body == {
        "properties": {"title": "Audit"},
        "sheets": [
            {
                "properties": {
                    "title": "Issues",
                    "gridProperties": {"frozenRowCount": 1},
                }
            },
            {
                "properties": {
                    "title": "Notes",
                    "gridProperties": {"frozenRowCount": 1},
                }
            },
        ],
    }


def test_spreadsheet_create_body_rejects_duplicate_sheet_titles():
    cli = load_cli_module()

    with pytest.raises(cli.CliError, match="不能重复"):
        cli.spreadsheet_create_body("Audit", ["Issues", "Issues"], 0)


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
    assert "references/google-workspace-oauth.md" in message
    assert "./scripts/gsheets_cli.py auth login" in message
