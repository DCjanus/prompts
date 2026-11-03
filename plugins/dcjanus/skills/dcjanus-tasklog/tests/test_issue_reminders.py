from __future__ import annotations

import json

import pytest
from rich.text import Text
from typer.testing import CliRunner

from . import test_linear_cli

linear_cli = test_linear_cli.linear_cli
document_client = test_linear_cli.document_client

ISSUE = {"id": "issue-id", "identifier": "SD-1", "title": "Review results"}
AT = "2099-11-03T16:40:00+08:00"
UTC_AT = "2099-11-03T08:40:00.000+00:00"


def notification(**overrides):
    """构造原生 IssueNotification 的最小提醒字段。"""
    return {
        "id": "reminder-id",
        "type": "issueReminder",
        "archivedAt": None,
        "snoozedUntilAt": "2099-11-03T08:40:00.000Z",
        "issue": {"id": ISSUE["id"], "identifier": ISSUE["identifier"]},
        **overrides,
    }


def page(*nodes, has_next=False, cursor=None):
    """构造可分页的通知响应。"""
    return {
        "notifications": {
            "nodes": list(nodes),
            "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
        }
    }


def test_reminder_help_documents_timestamp_and_preview():
    result = CliRunner().invoke(linear_cli.app, ["issue", "reminder", "set", "--help"])
    assert result.exit_code == 0, result.output
    help_text = Text.from_ansi(result.output).plain
    for expected in ["ISSUE_ID", "--at", "RFC3339", "时区", "--yes"]:
        assert expected in help_text


def test_reminder_set_previews_without_mutation(document_client):
    calls, replies = document_client
    replies.extend([{"issue": ISSUE}, page()])
    result = CliRunner().invoke(
        linear_cli.app, ["issue", "reminder", "set", "SD-1", "--at", AT]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["preview"] is True
    assert payload["input"] == {"id": "issue-id", "reminderAt": UTC_AT}
    assert all("mutation" not in call["query"] for call in calls)


def test_reminder_list_reads_all_pages_and_only_target_issue(document_client):
    calls, replies = document_client
    replies.extend(
        [
            {"issue": ISSUE},
            page(
                notification(issue={"id": "other-issue"}), has_next=True, cursor="next"
            ),
            page(
                notification(),
                notification(id="delivered", snoozedUntilAt=None),
                notification(id="past", snoozedUntilAt="2000-01-01T00:00:00Z"),
                notification(id="archived", archivedAt="2099-01-01T00:00:00Z"),
            ),
        ]
    )
    result = CliRunner().invoke(linear_cli.app, ["issue", "reminder", "list", "SD-1"])
    assert result.exit_code == 0, result.output
    assert [n["id"] for n in json.loads(result.output)["reminders"]] == ["reminder-id"]
    assert calls[-1]["variables"]["after"] == "next"


@pytest.mark.parametrize(
    ("at", "utc_at", "readback_at"),
    [
        (AT, UTC_AT, "2099-11-03T08:40:00.000Z"),
        (
            "2099-11-03T16:40:00.123456+08:00",
            "2099-11-03T08:40:00.123+00:00",
            "2099-11-03T08:40:00.123Z",
        ),
    ],
)
def test_reminder_set_uses_native_mutation_and_verifies_notification(
    document_client, at, utc_at, readback_at
):
    calls, replies = document_client
    replies.extend(
        [
            {"issue": ISSUE},
            page(),
            {"issueReminder": {"success": True, "issue": {"id": "issue-id"}}},
            page(notification(snoozedUntilAt=readback_at)),
        ]
    )
    result = CliRunner().invoke(
        linear_cli.app, ["issue", "reminder", "set", "SD-1", "--at", at, "--yes"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["reminder"]["id"] == "reminder-id"
    assert "issueReminder(id: $id, reminderAt: $reminderAt)" in calls[2]["query"]
    assert calls[2]["variables"] == {"id": "issue-id", "reminderAt": utc_at}
    assert "Notifications" in calls[3]["query"]


def test_reminder_set_does_not_duplicate_matching_reminder(document_client):
    calls, replies = document_client
    replies.extend([{"issue": ISSUE}, page(notification())])
    result = CliRunner().invoke(
        linear_cli.app, ["issue", "reminder", "set", "SD-1", "--at", AT, "--yes"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["unchanged"] is True
    assert all("mutation" not in call["query"] for call in calls)


@pytest.mark.parametrize(
    "at", ["2099-11-03", "2099-11-03T16:40:00", "2000-01-01T00:00:00Z", "invalid"]
)
def test_reminder_rejects_ambiguous_or_past_times_before_network(monkeypatch, at):
    def unexpected_client(*args, **kwargs):
        raise AssertionError("invalid time must not access Linear")

    monkeypatch.setattr(linear_cli, "get_client", unexpected_client)
    result = CliRunner().invoke(
        linear_cli.app, ["issue", "reminder", "set", "SD-1", "--at", at, "--yes"]
    )
    assert result.exit_code == 2, result.output


def test_reminder_reports_readback_failure_without_repeating_write(document_client):
    calls, replies = document_client
    replies.extend(
        [
            {"issue": ISSUE},
            page(),
            {"issueReminder": {"success": True, "issue": {"id": "issue-id"}}},
            page(notification(snoozedUntilAt="2099-11-04T08:40:00Z")),
        ]
    )
    result = CliRunner().invoke(
        linear_cli.app, ["issue", "reminder", "set", "SD-1", "--at", AT, "--yes"]
    )
    assert result.exit_code != 0
    assert "已执行" in str(result.exception)
    assert sum("mutation" in call["query"] for call in calls) == 1
