from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

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
    assert "auth import-client" in message


@pytest.mark.parametrize(
    ("args", "extra"),
    [
        ([], {}),
        (["--include-grid-data"], {"includeGridData": True}),
        (
            ["--range", "'Sheet 1'!A1:B2", "--range", "Other!C3"],
            {"ranges": ["'Sheet 1'!A1:B2", "Other!C3"]},
        ),
        (
            ["--range", "Sheet1!A1", "--fields", "sheets(data(rowData))"],
            {"ranges": ["Sheet1!A1"], "fields": "sheets(data(rowData))"},
        ),
    ],
)
def test_spreadsheet_get_passes_native_query_options(monkeypatch, args, extra):
    cli = load_cli_module()
    service = MagicMock()
    service.spreadsheets.return_value.get.return_value.execute.return_value = {
        "spreadsheetId": "example"
    }
    monkeypatch.setattr(cli, "get_service", lambda: service)
    result = CliRunner().invoke(
        cli.app,
        ["--json", "spreadsheet", "get", "--spreadsheet-id", "example", *args],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"spreadsheetId": "example"}
    service.spreadsheets.return_value.get.assert_called_once_with(
        **{"spreadsheetId": "example", "includeGridData": False, **extra}
    )


@pytest.fixture
def client_import(monkeypatch, tmp_path):
    cli = load_cli_module()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    source = tmp_path / "download.json"
    source.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "test-client",
                    "client_secret": "private-test-value",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            }
        )
    )
    return cli, source


def test_import_client_command_secures_file_without_exposing_secret(client_import):
    cli, source = client_import
    cli.config_dir().mkdir(parents=True, mode=0o755)
    cli.token_path().write_text("existing-token")
    original = source.read_bytes()
    result = CliRunner().invoke(
        cli.app, ["--json", "auth", "import-client", str(source)]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "status": "ok",
        "client_secret": str(cli.client_secret_path()),
    }
    assert "private-test-value" not in result.output
    assert cli.client_secret_path().read_bytes() == original == source.read_bytes()
    assert cli.client_secret_path().stat().st_mode & 0o777 == 0o600
    assert cli.config_dir().stat().st_mode & 0o777 == 0o700
    assert cli.token_path().read_text() == "existing-token"
    flow = cli.InstalledAppFlow.from_client_secrets_file(
        str(cli.client_secret_path()), cli.SCOPES
    )
    assert flow.client_config["client_id"] == "test-client"


@pytest.mark.parametrize(
    "invalid",
    [b"not-json", b"\xff", b"[]", b'{"web": {}}', b'{"installed": {"client_id": 3}}'],
)
def test_import_rejects_invalid_download_before_creating_config(client_import, invalid):
    cli, source = client_import
    source.write_bytes(invalid)
    with pytest.raises(cli.CliError):
        cli.import_client_secret(source)
    assert not cli.config_dir().exists()


def test_import_requires_explicit_overwrite_and_preserves_token(client_import):
    cli, source = client_import
    cli.config_dir().mkdir(parents=True)
    cli.client_secret_path().write_text("old-client")
    cli.token_path().write_text("old-token")
    with pytest.raises(cli.CliError, match="--overwrite"):
        cli.import_client_secret(source)
    assert cli.client_secret_path().read_text() == "old-client"
    result = CliRunner().invoke(
        cli.app, ["auth", "import-client", str(source), "--overwrite"]
    )
    assert result.exit_code == 0, result.output
    assert cli.client_secret_path().read_bytes() == source.read_bytes()
    assert cli.token_path().read_text() == "old-token"


@pytest.mark.parametrize("link_directory", [False, True])
def test_import_rejects_destination_symlinks(client_import, tmp_path, link_directory):
    cli, source = client_import
    cli.config_dir().parent.mkdir(parents=True)
    if link_directory:
        external = tmp_path / "external-dir"
        external.mkdir()
        cli.config_dir().symlink_to(external, target_is_directory=True)
    else:
        cli.config_dir().mkdir()
        cli.client_secret_path().symlink_to(source)
    original = source.read_bytes()
    with pytest.raises(cli.CliError, match="软链接"):
        cli.import_client_secret(source, overwrite=True)
    assert source.read_bytes() == original


def test_failed_import_preserves_existing_file_and_removes_temporary(
    client_import, monkeypatch
):
    cli, source = client_import
    cli.config_dir().mkdir(parents=True)
    cli.client_secret_path().write_text("old-client")

    def fail_replace(*args):
        raise OSError("private-test-value")

    monkeypatch.setattr(cli.os, "replace", fail_replace)
    with pytest.raises(cli.CliError, match="导入失败") as error:
        cli.import_client_secret(source, overwrite=True)
    assert "private-test-value" not in str(error.value)
    assert cli.client_secret_path().read_text() == "old-client"
    assert list(cli.config_dir().iterdir()) == [cli.client_secret_path()]


def test_import_does_not_overwrite_file_created_during_import(
    client_import, monkeypatch
):
    cli, source = client_import
    original_link = cli.os.link

    def competing_import(source_path, target_path):
        target_path.write_text("other-client")
        original_link(source_path, target_path)

    monkeypatch.setattr(cli.os, "link", competing_import)
    with pytest.raises(cli.CliError, match="--overwrite"):
        cli.import_client_secret(source)
    assert cli.client_secret_path().read_text() == "other-client"
    assert list(cli.config_dir().iterdir()) == [cli.client_secret_path()]
