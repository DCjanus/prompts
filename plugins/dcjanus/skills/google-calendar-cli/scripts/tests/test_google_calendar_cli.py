from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "google_calendar_cli.py"


def load_cli_module():
    spec = importlib.util.spec_from_file_location("google_calendar_cli", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_client_secret_reuses_shared_secret_and_keeps_token_separate(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("GOOGLE_WORKSPACE_CLIENT_SECRET", raising=False)
    shared_secret = tmp_path / "google-workspace-cli" / "client_secret.json"
    shared_secret.parent.mkdir()
    shared_secret.write_text("{}", encoding="utf-8")
    cli = load_cli_module()

    assert cli.client_secret_path() == shared_secret
    assert cli.token_path() == tmp_path / "google-calendar-cli" / "token.json"


def test_client_secret_falls_back_to_existing_sheets_secret(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("GOOGLE_WORKSPACE_CLIENT_SECRET", raising=False)
    sheets_secret = tmp_path / "google-sheets-cli" / "client_secret.json"
    sheets_secret.parent.mkdir()
    sheets_secret.write_text("{}", encoding="utf-8")
    cli = load_cli_module()

    assert cli.client_secret_path() == sheets_secret


def test_explicit_client_secret_path_has_priority(monkeypatch, tmp_path):
    configured = tmp_path / "oauth" / "desktop.json"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("GOOGLE_WORKSPACE_CLIENT_SECRET", str(configured))
    cli = load_cli_module()

    assert cli.client_secret_path() == configured


def test_write_token_uses_private_permissions_and_atomic_replacement(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cli = load_cli_module()

    class Credentials:
        def to_json(self):
            return json.dumps({"refresh_token": "test-only"})

    cli.write_token(Credentials())

    assert cli.config_dir().stat().st_mode & 0o777 == 0o700
    assert cli.token_path().stat().st_mode & 0o777 == 0o600
    assert json.loads(cli.token_path().read_text(encoding="utf-8")) == {
        "refresh_token": "test-only"
    }
    assert list(cli.config_dir().glob(".token-*.json")) == []


def test_required_scopes_are_narrow_and_do_not_include_full_calendar_scope():
    cli = load_cli_module()

    assert "https://www.googleapis.com/auth/calendar" not in cli.SCOPES
    assert cli.SCOPES == [
        "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/calendar.events.freebusy",
    ]


@pytest.mark.parametrize(
    "time_min,time_max,message",
    [
        ("2026-09-04T10:00:00", None, "时区"),
        ("not-a-time", None, "RFC3339"),
        (
            "2026-09-04T11:00:00+08:00",
            "2026-09-04T10:00:00+08:00",
            "晚于",
        ),
    ],
)
def test_time_window_rejects_invalid_or_reversed_values(time_min, time_max, message):
    cli = load_cli_module()

    with pytest.raises(cli.CliError, match=message):
        cli.ensure_time_window(time_min, time_max)


def test_event_create_body_accepts_timed_and_all_day_events():
    cli = load_cli_module()
    timed = {
        "summary": "sync",
        "start": {"dateTime": "2026-09-04T10:00:00+08:00"},
        "end": {"dateTime": "2026-09-04T10:30:00+08:00"},
    }
    all_day = {
        "summary": "holiday",
        "start": {"date": "2026-09-04"},
        "end": {"date": "2026-09-05"},
    }
    named_time_zone = {
        "summary": "weekly sync",
        "start": {
            "dateTime": "2026-09-04T10:00:00",
            "timeZone": "Asia/Shanghai",
        },
        "end": {
            "dateTime": "2026-09-04T10:30:00",
            "timeZone": "Asia/Shanghai",
        },
    }

    assert cli.validate_event_body(timed, "--event-json", create=True) == timed
    assert cli.validate_event_body(all_day, "--event-json", create=True) == all_day
    assert (
        cli.validate_event_body(named_time_zone, "--event-json", create=True)
        == named_time_zone
    )


@pytest.mark.parametrize(
    "value,message",
    [
        ({"summary": "missing times"}, "缺少字段"),
        (
            {
                "start": {"date": "2026-09-04"},
                "end": {"dateTime": "2026-09-05T00:00:00+08:00"},
            },
            "同时使用",
        ),
        (
            {
                "start": {"dateTime": "2026-09-04T11:00:00+08:00"},
                "end": {"dateTime": "2026-09-04T10:00:00+08:00"},
            },
            "晚于",
        ),
    ],
)
def test_event_create_body_rejects_invalid_contract(value, message):
    cli = load_cli_module()

    with pytest.raises(cli.CliError, match=message):
        cli.validate_event_body(value, "--event-json", create=True)


def test_write_operations_require_explicit_confirmation():
    cli = load_cli_module()

    with pytest.raises(cli.CliError, match="--confirm-delete"):
        cli.require_confirmation(False, "--confirm-delete", "删除事件")

    cli.require_confirmation(True, "--confirm-delete", "删除事件")


def test_event_create_passes_notification_and_conference_controls(monkeypatch):
    cli = load_cli_module()
    captured = {}

    class ApiRequest:
        def execute(self):
            return {"id": "event-1"}

    class Events:
        def insert(self, **kwargs):
            captured.update(kwargs)
            return ApiRequest()

    class Service:
        def events(self):
            return Events()

    monkeypatch.setattr(cli, "get_service", Service)
    monkeypatch.setattr(
        cli, "render_output", lambda _ctx, value: captured.update(output=value)
    )
    body = {
        "summary": "sync",
        "start": {"dateTime": "2026-09-04T10:00:00+08:00"},
        "end": {"dateTime": "2026-09-04T10:30:00+08:00"},
    }

    cli.events_create(
        None,
        event_json=json.dumps(body),
        calendar_id="primary",
        send_updates=cli.SendUpdates.all,
        conference_data_version=1,
        confirm_create=True,
    )

    assert captured["calendarId"] == "primary"
    assert captured["body"] == body
    assert captured["sendUpdates"] == "all"
    assert captured["conferenceDataVersion"] == 1
    assert captured["output"] == {"id": "event-1"}


def test_events_list_defaults_to_expanded_start_order(monkeypatch):
    cli = load_cli_module()
    captured = {}

    class ApiRequest:
        def execute(self):
            return {"items": []}

    class Events:
        def list(self, **kwargs):
            captured.update(kwargs)
            return ApiRequest()

    class Service:
        def events(self):
            return Events()

    monkeypatch.setattr(cli, "get_service", Service)
    monkeypatch.setattr(cli, "render_output", lambda _ctx, _value: None)

    cli.events_list(
        None,
        calendar_id="primary",
        time_min="2026-09-04T00:00:00+08:00",
        time_max="2026-09-05T00:00:00+08:00",
        query=None,
        max_results=50,
        page_token=None,
        single_events=True,
        order_by=cli.EventOrder.start_time,
        show_deleted=False,
    )

    assert captured == {
        "calendarId": "primary",
        "maxResults": 50,
        "singleEvents": True,
        "showDeleted": False,
        "timeMin": "2026-09-04T00:00:00+08:00",
        "timeMax": "2026-09-05T00:00:00+08:00",
        "orderBy": "startTime",
    }


def test_freebusy_query_builds_multi_calendar_body(monkeypatch):
    cli = load_cli_module()
    captured = {}

    class ApiRequest:
        def execute(self):
            return {"calendars": {}}

    class Freebusy:
        def query(self, **kwargs):
            captured.update(kwargs)
            return ApiRequest()

    class Service:
        def freebusy(self):
            return Freebusy()

    monkeypatch.setattr(cli, "get_service", Service)
    monkeypatch.setattr(cli, "render_output", lambda _ctx, _value: None)

    cli.freebusy_query(
        None,
        calendar_ids=["one@example.com", "two@example.com"],
        time_min="2026-09-04T09:00:00+08:00",
        time_max="2026-09-04T18:00:00+08:00",
        time_zone="Asia/Shanghai",
        group_expansion_max=100,
        calendar_expansion_max=50,
    )

    assert captured["body"]["items"] == [
        {"id": "one@example.com"},
        {"id": "two@example.com"},
    ]
    assert captured["body"]["timeZone"] == "Asia/Shanghai"
