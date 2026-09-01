from __future__ import annotations

import base64
import importlib.util
from email import policy
from email.parser import BytesParser
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "google_mail_cli.py"


def load_cli_module():
    spec = importlib.util.spec_from_file_location("google_mail_cli", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_client_secret_reuses_existing_sheets_secret(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("GOOGLE_WORKSPACE_CLIENT_SECRET", raising=False)
    sheets_secret = tmp_path / "google-sheets-cli" / "client_secret.json"
    sheets_secret.parent.mkdir()
    sheets_secret.write_text("{}", encoding="utf-8")
    cli = load_cli_module()

    assert cli.client_secret_path() == sheets_secret
    assert cli.token_path() == tmp_path / "google-mail-cli" / "token.json"


def test_explicit_client_secret_path_has_priority(monkeypatch, tmp_path):
    configured = tmp_path / "oauth" / "desktop.json"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("GOOGLE_WORKSPACE_CLIENT_SECRET", str(configured))
    cli = load_cli_module()

    assert cli.client_secret_path() == configured


def test_normalize_message_decodes_multipart_body_and_attachment():
    cli = load_cli_module()
    encoded_text = base64.urlsafe_b64encode("你好 Gmail".encode()).decode()
    message = {
        "id": "message-1",
        "threadId": "thread-1",
        "snippet": "你好",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "From", "value": "sender@example.com"},
                {"name": "Subject", "value": "测试"},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "headers": [
                        {
                            "name": "Content-Type",
                            "value": "text/plain; charset=utf-8",
                        }
                    ],
                    "body": {"data": encoded_text},
                },
                {
                    "mimeType": "application/pdf",
                    "filename": "report.pdf",
                    "body": {"attachmentId": "attachment-1", "size": 42},
                },
            ],
        },
    }

    result = cli.normalize_message(message)

    assert result["headers"]["From"] == "sender@example.com"
    assert result["textBody"] == "你好 Gmail"
    assert result["attachments"] == [
        {
            "filename": "report.pdf",
            "mimeType": "application/pdf",
            "size": 42,
            "attachmentId": "attachment-1",
        }
    ]


def test_build_message_resource_preserves_headers_bodies_and_attachment(tmp_path):
    cli = load_cli_module()
    attachment = tmp_path / "note.txt"
    attachment.write_text("attachment body", encoding="utf-8")

    resource = cli.build_message_resource(
        from_address="me@example.com",
        to=["to@example.com"],
        cc=["cc@example.com"],
        bcc=[],
        subject="Subject",
        body_text="plain body",
        body_html="<p>html body</p>",
        attachments=[attachment],
        thread_id="thread-1",
        in_reply_to="<original@example.com>",
        references="<original@example.com>",
    )
    parsed = BytesParser(policy=policy.default).parsebytes(
        cli.decode_base64url(resource["raw"])
    )

    assert resource["threadId"] == "thread-1"
    assert parsed["From"] == "me@example.com"
    assert parsed["To"] == "to@example.com"
    assert parsed["In-Reply-To"] == "<original@example.com>"
    assert parsed.get_body(preferencelist=("plain",)).get_content() == "plain body\n"
    assert parsed.get_body(preferencelist=("html",)).get_content() == (
        "<p>html body</p>\n"
    )
    assert [part.get_filename() for part in parsed.iter_attachments()] == ["note.txt"]


def test_filter_validation_accepts_supported_contract():
    cli = load_cli_module()
    value = {
        "criteria": {"from": "sender@example.com", "hasAttachment": True},
        "action": {"addLabelIds": ["Label_1"], "removeLabelIds": ["INBOX"]},
    }

    assert cli.validate_filter(value) == value


@pytest.mark.parametrize(
    "value, message",
    [
        ({"criteria": {}, "action": {"addLabelIds": ["Label_1"]}}, "criteria"),
        (
            {"criteria": {"from": "a@example.com"}, "action": {"unknown": True}},
            "未知字段",
        ),
        (
            {"criteria": {"from": "a@example.com"}, "action": {"addLabelIds": []}},
            "非空字符串数组",
        ),
        (
            {
                "criteria": {"size": 10, "sizeComparison": "equal"},
                "action": {"removeLabelIds": ["INBOX"]},
            },
            "smaller",
        ),
    ],
)
def test_filter_validation_rejects_unsafe_or_unknown_shapes(value, message):
    cli = load_cli_module()

    with pytest.raises(cli.CliError, match=message):
        cli.validate_filter(value)


def test_high_risk_operations_require_explicit_confirmation():
    cli = load_cli_module()

    with pytest.raises(cli.CliError, match="--confirm-send"):
        cli.require_confirmation(False, "--confirm-send", "发送邮件")

    cli.require_confirmation(True, "--confirm-send", "发送邮件")


def test_labels_update_patches_only_requested_fields(monkeypatch):
    cli = load_cli_module()
    captured = {}

    class Request:
        def execute(self):
            return {"id": "Label_1", "name": "New Name"}

    class Labels:
        def patch(self, **kwargs):
            captured.update(kwargs)
            return Request()

    class Users:
        def labels(self):
            return Labels()

    class Service:
        def users(self):
            return Users()

    monkeypatch.setattr(cli, "get_service", Service)
    monkeypatch.setattr(
        cli, "render_output", lambda _ctx, value: captured.update(output=value)
    )

    cli.labels_update(
        None,
        label_id="Label_1",
        name="New Name",
        label_list_visibility=None,
        message_list_visibility=None,
        confirm_update=True,
    )

    assert captured["userId"] == "me"
    assert captured["id"] == "Label_1"
    assert captured["body"] == {"name": "New Name"}
    assert captured["output"] == {"id": "Label_1", "name": "New Name"}


def test_attachment_download_refuses_implicit_overwrite(tmp_path):
    cli = load_cli_module()
    output = tmp_path / "attachment.bin"

    cli.write_download(b"first", output, overwrite=False)

    assert output.read_bytes() == b"first"
    assert output.stat().st_mode & 0o777 == 0o600
    with pytest.raises(cli.CliError, match="--overwrite"):
        cli.write_download(b"second", output, overwrite=False)

    cli.write_download(b"second", output, overwrite=True)
    assert output.read_bytes() == b"second"
