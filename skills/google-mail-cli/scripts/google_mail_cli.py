#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "google-api-python-client>=2.200.0",
#     "google-auth-httplib2>=0.4.2",
#     "google-auth-oauthlib>=1.4.1",
#     "rich>=15.0.0",
#     "typer>=0.27.2",
# ]
# ///

"""面向 Codex skill 的 Gmail API 命令行工具。"""

# Typer 以 Option(...) 作为声明式参数元数据，B008 在这里不适用。
# ruff: noqa: B008

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import tempfile
from email.header import decode_header, make_header
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import typer
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from rich.console import Console
from rich.pretty import Pretty

APP_NAME = "google-mail-cli"
CLIENT_SECRET_ENV = "GOOGLE_WORKSPACE_CLIENT_SECRET"
CLIENT_SECRET_FILENAME = "client_secret.json"
TOKEN_FILENAME = "token.json"
AUTH_DOC = "references/google-workspace-oauth.md"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.settings.basic",
]
DISPLAY_HEADERS = (
    "From",
    "To",
    "Cc",
    "Bcc",
    "Reply-To",
    "Subject",
    "Date",
    "Message-ID",
    "In-Reply-To",
    "References",
)
FILTER_CRITERIA_FIELDS = {
    "from",
    "to",
    "subject",
    "query",
    "negatedQuery",
    "hasAttachment",
    "excludeChats",
    "size",
    "sizeComparison",
}
FILTER_ACTION_FIELDS = {"addLabelIds", "removeLabelIds", "forward"}

app = typer.Typer(no_args_is_help=True)
auth_app = typer.Typer(no_args_is_help=True, help="认证相关操作。")
messages_app = typer.Typer(no_args_is_help=True, help="搜索、读取和整理邮件。")
threads_app = typer.Typer(no_args_is_help=True, help="读取和整理邮件线程。")
labels_app = typer.Typer(no_args_is_help=True, help="查看、创建和更新标签。")
drafts_app = typer.Typer(no_args_is_help=True, help="查看、创建和更新草稿。")
send_app = typer.Typer(no_args_is_help=True, help="发送新邮件或已有草稿。")
filters_app = typer.Typer(no_args_is_help=True, help="查看和配置过滤规则。")
attachments_app = typer.Typer(no_args_is_help=True, help="下载邮件附件。")
console = Console()


class CliError(RuntimeError):
    """面向用户展示的 CLI 错误。"""


def xdg_config_home() -> Path:
    """返回 XDG 配置目录。"""
    value = os.environ.get("XDG_CONFIG_HOME")
    if value:
        return Path(value).expanduser()
    return Path.home() / ".config"


def config_dir() -> Path:
    """返回 Gmail token 的独立配置目录。"""
    return xdg_config_home() / APP_NAME


def client_secret_candidates() -> list[Path]:
    """按优先级返回可复用的 OAuth client secret 路径。"""
    candidates: list[Path] = []
    configured = os.environ.get(CLIENT_SECRET_ENV)
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend(
        [
            xdg_config_home() / "google-workspace-cli" / CLIENT_SECRET_FILENAME,
            xdg_config_home() / "google-sheets-cli" / CLIENT_SECRET_FILENAME,
        ]
    )
    return candidates


def client_secret_path() -> Path:
    """返回明确配置的或第一个存在的 OAuth client secret。"""
    candidates = client_secret_candidates()
    if os.environ.get(CLIENT_SECRET_ENV):
        return candidates[0]
    return next((path for path in candidates if path.exists()), candidates[0])


def token_path() -> Path:
    """返回 Gmail 专用 token 路径。"""
    return config_dir() / TOKEN_FILENAME


def credential_paths_payload() -> dict[str, Any]:
    """返回不包含凭据内容的认证路径信息。"""
    selected = client_secret_path()
    return {
        "config_dir": str(config_dir()),
        "client_secret": str(selected),
        "client_secret_source": (
            "environment"
            if os.environ.get(CLIENT_SECRET_ENV)
            else "first_existing_candidate"
        ),
        "client_secret_candidates": [
            {"path": str(path), "exists": path.exists()}
            for path in client_secret_candidates()
        ],
        "token": str(token_path()),
    }


def missing_client_secret_message(path: Path) -> str:
    """生成可执行的 client secret 缺失提示。"""
    return f"""缺少 Google OAuth Desktop client secret：{path}

可选处理方式：
1. 把共享凭据保存到 ~/.config/google-workspace-cli/client_secret.json；或
2. 直接复用 ~/.config/google-sheets-cli/client_secret.json；或
3. 设置 {CLIENT_SECRET_ENV} 指向已有 JSON。

然后运行：./scripts/google_mail_cli.py auth login
详细配置见 {AUTH_DOC}。"""


def missing_token_message(path: Path) -> str:
    """生成可执行的 token 缺失提示。"""
    return f"""缺少 Gmail OAuth token：{path}

运行：./scripts/google_mail_cli.py auth login
Gmail token 与 Google Sheets token 分开保存，不能直接复制复用。
详细配置见 {AUTH_DOC}。"""


def ensure_client_secret_exists() -> Path:
    """确认 OAuth client secret 存在。"""
    path = client_secret_path()
    if not path.exists():
        raise CliError(missing_client_secret_message(path))
    return path


def missing_scopes(credentials: Credentials) -> list[str]:
    """返回 token 尚未授权的必要 scope。"""
    return [scope for scope in SCOPES if not credentials.has_scopes([scope])]


def write_token(credentials: Credentials) -> None:
    """以仅当前用户可读写的方式原子保存 token。"""
    directory = config_dir()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    destination = token_path()
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=directory,
        prefix=".token-",
        suffix=".json",
        delete=False,
    ) as file:
        temporary = Path(file.name)
        file.write(credentials.to_json())
    temporary.chmod(0o600)
    temporary.replace(destination)
    destination.chmod(0o600)


def load_credentials() -> Credentials:
    """读取、校验并按需刷新 Gmail OAuth token。"""
    ensure_client_secret_exists()
    path = token_path()
    if not path.exists():
        raise CliError(missing_token_message(path))
    try:
        credentials = Credentials.from_authorized_user_file(str(path), SCOPES)
    except (ValueError, GoogleAuthError) as exc:
        raise CliError(
            f"Gmail token 无法读取或格式不正确：{path}\n"
            "请执行 auth logout 后重新执行 auth login。"
        ) from exc
    missing = missing_scopes(credentials)
    if missing:
        raise CliError(
            "Gmail token 缺少必要 scope：\n- "
            + "\n- ".join(missing)
            + "\nDesktop app 不支持增量授权，请执行 auth logout 后重新登录。"
        )
    if credentials.valid:
        return credentials
    if credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except GoogleAuthError as exc:
            raise CliError(
                "Gmail token 刷新失败，可能是授权被撤销、scope 变化或 Workspace "
                "策略阻止。请重新执行 auth login。"
            ) from exc
        write_token(credentials)
        return credentials
    raise CliError("Gmail token 无效且无法刷新，请重新执行 auth login。")


def get_service() -> Any:
    """构造 Gmail API v1 client。"""
    return build(
        "gmail",
        "v1",
        credentials=load_credentials(),
        cache_discovery=False,
    )


def render_output(ctx: typer.Context, payload: Any) -> None:
    """根据全局参数输出 JSON 或人类可读结构。"""
    if ctx.obj and ctx.obj.get("json_output"):
        console.print_json(data=payload)
        return
    console.print(Pretty(payload, expand_all=True))


def http_error_message(exc: HttpError) -> CliError:
    """把 Gmail API 错误转换为可操作提示。"""
    status = getattr(getattr(exc, "resp", None), "status", None)
    try:
        payload = json.loads(exc.content.decode("utf-8"))
        message = payload.get("error", {}).get("message") or str(exc)
    except (AttributeError, json.JSONDecodeError, UnicodeDecodeError):
        message = str(exc)
    hint = ""
    if status in {401, 403}:
        hint = (
            "\n请确认 Gmail API 已启用、OAuth consent screen 已添加 Gmail scopes，"
            "且 Workspace API Controls 允许当前 Client ID。"
        )
    if status == 404:
        hint = "\n请确认资源 ID 属于当前登录账号且仍然存在。"
    return CliError(f"Gmail API 请求失败（status {status}）：{message}{hint}")


def execute(request: Any) -> Any:
    """统一执行 Gmail API 请求并转换错误。"""
    try:
        return request.execute()
    except HttpError as exc:
        raise http_error_message(exc) from exc


def decode_base64url(data: str) -> bytes:
    """解码 Gmail 使用的无填充 base64URL。"""
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def decode_header_value(value: str) -> str:
    """解码 RFC 2047 邮件头。"""
    try:
        return str(make_header(decode_header(value)))
    except (LookupError, UnicodeDecodeError):
        return value


def selected_headers(payload: dict[str, Any]) -> dict[str, str]:
    """提取适合 Agent 阅读的常见邮件头。"""
    available = {
        str(item.get("name", "")).lower(): decode_header_value(
            str(item.get("value", ""))
        )
        for item in payload.get("headers", [])
        if item.get("name")
    }
    return {
        name: available[name.lower()]
        for name in DISPLAY_HEADERS
        if name.lower() in available
    }


def charset_for_part(part: dict[str, Any]) -> str:
    """从 Content-Type 头提取 charset。"""
    headers = {
        str(item.get("name", "")).lower(): str(item.get("value", ""))
        for item in part.get("headers", [])
    }
    match = re.search(
        r"charset\s*=\s*[\"']?([^;\s\"']+)",
        headers.get("content-type", ""),
        re.IGNORECASE,
    )
    return match.group(1) if match else "utf-8"


def collect_payload_content(
    part: dict[str, Any],
) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    """递归提取 MIME payload 中的正文和附件元数据。"""
    text_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[dict[str, Any]] = []
    filename = str(part.get("filename", ""))
    mime_type = str(part.get("mimeType", "application/octet-stream"))
    body = part.get("body") or {}
    attachment_id = body.get("attachmentId")
    if filename or attachment_id:
        attachments.append(
            {
                "filename": filename,
                "mimeType": mime_type,
                "size": body.get("size"),
                "attachmentId": attachment_id,
            }
        )
    data = body.get("data")
    if data and mime_type in {"text/plain", "text/html"}:
        raw = decode_base64url(str(data))
        charset = charset_for_part(part)
        try:
            decoded = raw.decode(charset)
        except (LookupError, UnicodeDecodeError):
            decoded = raw.decode("utf-8", errors="replace")
        (html_parts if mime_type == "text/html" else text_parts).append(decoded)
    for child in part.get("parts") or []:
        child_text, child_html, child_attachments = collect_payload_content(child)
        text_parts.extend(child_text)
        html_parts.extend(child_html)
        attachments.extend(child_attachments)
    return text_parts, html_parts, attachments


def normalize_message(
    message: dict[str, Any], *, include_body: bool = True
) -> dict[str, Any]:
    """把 Gmail Message 转换为稳定、易读的结构。"""
    payload = message.get("payload") or {}
    text_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[dict[str, Any]] = []
    if include_body:
        text_parts, html_parts, attachments = collect_payload_content(payload)
    result: dict[str, Any] = {
        key: message.get(key)
        for key in (
            "id",
            "threadId",
            "labelIds",
            "snippet",
            "historyId",
            "internalDate",
            "sizeEstimate",
        )
        if key in message
    }
    result["headers"] = selected_headers(payload)
    if include_body:
        result["textBody"] = "\n".join(text_parts) or None
        result["htmlBody"] = "\n".join(html_parts) or None
        result["attachments"] = attachments
    return result


def load_json_arg(raw: str, option_name: str) -> Any:
    """读取直接传入或 @path 指向的 JSON。"""
    source = raw
    if raw.startswith("@"):
        path = Path(raw[1:]).expanduser()
        if not path.exists():
            raise CliError(f"{option_name} 指向的文件不存在：{path}")
        source = path.read_text(encoding="utf-8")
    try:
        return json.loads(source)
    except json.JSONDecodeError as exc:
        raise CliError(f"{option_name} 不是合法 JSON：{exc}") from exc


def validate_filter(value: Any) -> dict[str, Any]:
    """校验 Gmail filter 的公开契约与字段范围。"""
    if not isinstance(value, dict):
        raise CliError("--filter-json 必须是 JSON 对象。")
    unknown_root = set(value) - {"criteria", "action"}
    if unknown_root:
        raise CliError(f"--filter-json 包含未知字段：{sorted(unknown_root)}")
    criteria = value.get("criteria")
    action = value.get("action")
    if not isinstance(criteria, dict) or not criteria:
        raise CliError("--filter-json.criteria 必须是非空对象。")
    if not isinstance(action, dict) or not action:
        raise CliError("--filter-json.action 必须是非空对象。")
    unknown_criteria = set(criteria) - FILTER_CRITERIA_FIELDS
    unknown_action = set(action) - FILTER_ACTION_FIELDS
    if unknown_criteria:
        raise CliError(f"criteria 包含未知字段：{sorted(unknown_criteria)}")
    if unknown_action:
        raise CliError(f"action 包含未知字段：{sorted(unknown_action)}")
    for field in ("from", "to", "subject", "query", "negatedQuery"):
        if field in criteria and (
            not isinstance(criteria[field], str) or not criteria[field]
        ):
            raise CliError(f"criteria.{field} 必须是非空字符串。")
    for field in ("hasAttachment", "excludeChats"):
        if field in criteria and not isinstance(criteria[field], bool):
            raise CliError(f"criteria.{field} 必须是 boolean。")
    if "size" in criteria and (
        not isinstance(criteria["size"], int)
        or isinstance(criteria["size"], bool)
        or criteria["size"] < 0
    ):
        raise CliError("criteria.size 必须是非负整数。")
    if "sizeComparison" in criteria and criteria["sizeComparison"] not in {
        "smaller",
        "larger",
    }:
        raise CliError("criteria.sizeComparison 只能是 smaller 或 larger。")
    for field in ("addLabelIds", "removeLabelIds"):
        if field in action and (
            not isinstance(action[field], list)
            or not action[field]
            or any(not isinstance(item, str) or not item for item in action[field])
        ):
            raise CliError(f"action.{field} 必须是非空字符串数组。")
    if "forward" in action and (
        not isinstance(action["forward"], str) or not action["forward"]
    ):
        raise CliError("action.forward 必须是非空字符串。")
    return {"criteria": criteria, "action": action}


def write_download(data: bytes, output: Path, *, overwrite: bool) -> None:
    """把下载内容原子写入明确路径，并默认拒绝覆盖。"""
    destination = output.expanduser()
    if destination.exists() and not overwrite:
        raise CliError(f"输出文件已存在：{destination}；确认覆盖后添加 --overwrite。")
    if not destination.parent.is_dir():
        raise CliError(f"输出目录不存在：{destination.parent}")
    with tempfile.NamedTemporaryFile(
        dir=destination.parent,
        prefix=f".{destination.name}-",
        delete=False,
    ) as file:
        temporary = Path(file.name)
        file.write(data)
    temporary.chmod(0o600)
    temporary.replace(destination)
    destination.chmod(0o600)


def read_body_value(
    direct: str | None, path: Path | None, option_name: str
) -> str | None:
    """读取直接正文或文件正文，并拒绝歧义输入。"""
    if direct is not None and path is not None:
        raise CliError(f"{option_name} 与对应文件参数不能同时使用。")
    if path is not None:
        if not path.is_file():
            raise CliError(f"正文文件不存在或不是普通文件：{path}")
        return path.read_text(encoding="utf-8")
    return direct


def build_message_resource(
    *,
    from_address: str,
    to: list[str],
    cc: list[str],
    bcc: list[str],
    subject: str,
    body_text: str | None,
    body_html: str | None,
    attachments: list[Path],
    thread_id: str | None,
    in_reply_to: str | None,
    references: str | None,
) -> dict[str, Any]:
    """构造 Gmail API 需要的 MIME message resource。"""
    if not to and not cc and not bcc:
        raise CliError("至少需要一个 --to、--cc 或 --bcc 收件人。")
    if body_text is None and body_html is None:
        raise CliError("至少需要提供纯文本或 HTML 正文。")
    message = EmailMessage()
    message["From"] = from_address
    if to:
        message["To"] = ", ".join(to)
    if cc:
        message["Cc"] = ", ".join(cc)
    if bcc:
        message["Bcc"] = ", ".join(bcc)
    message["Subject"] = subject
    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
    if references:
        message["References"] = references
    if body_text is not None:
        message.set_content(body_text)
        if body_html is not None:
            message.add_alternative(body_html, subtype="html")
    else:
        message.set_content(body_html or "", subtype="html")
    for path in attachments:
        if not path.is_file():
            raise CliError(f"附件不存在或不是普通文件：{path}")
        mime_type, encoding = mimetypes.guess_type(path.name)
        if encoding or not mime_type:
            mime_type = "application/octet-stream"
        maintype, subtype = mime_type.split("/", 1)
        message.add_attachment(
            path.read_bytes(),
            maintype=maintype,
            subtype=subtype,
            filename=path.name,
        )
    resource: dict[str, Any] = {
        "raw": base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    }
    if thread_id:
        resource["threadId"] = thread_id
    return resource


def current_email_address(service: Any, from_address: str | None) -> str:
    """返回显式 From 或当前 Gmail 账号地址。"""
    if from_address:
        return from_address
    profile = execute(service.users().getProfile(userId="me"))
    return str(profile["emailAddress"])


def compose_resource(
    service: Any,
    *,
    from_address: str | None,
    to: list[str] | None,
    cc: list[str] | None,
    bcc: list[str] | None,
    subject: str,
    body: str | None,
    body_file: Path | None,
    html_body: str | None,
    html_body_file: Path | None,
    attachment: list[Path] | None,
    thread_id: str | None,
    in_reply_to: str | None,
    references: str | None,
) -> dict[str, Any]:
    """从 CLI 参数构造 message resource。"""
    return build_message_resource(
        from_address=current_email_address(service, from_address),
        to=to or [],
        cc=cc or [],
        bcc=bcc or [],
        subject=subject,
        body_text=read_body_value(body, body_file, "--body"),
        body_html=read_body_value(html_body, html_body_file, "--html-body"),
        attachments=attachment or [],
        thread_id=thread_id,
        in_reply_to=in_reply_to,
        references=references,
    )


def require_confirmation(value: bool, flag: str, action: str) -> None:
    """阻止未显式确认的高风险写操作。"""
    if not value:
        raise CliError(f"{action}需要显式确认；核对目标与内容后添加 {flag}。")


@app.callback()
def main(
    ctx: typer.Context,
    json_output: bool = typer.Option(
        False, "--json", help="输出 JSON，方便 Agent 解析。"
    ),
) -> None:
    """初始化全局输出选项。"""
    ctx.obj = {"json_output": json_output}


@auth_app.command("paths", help="显示凭据候选路径，不读取凭据内容。")
def auth_paths(ctx: typer.Context) -> None:
    """显示认证路径。"""
    payload = credential_paths_payload()
    payload["client_secret_exists"] = client_secret_path().exists()
    payload["token_exists"] = token_path().exists()
    render_output(ctx, payload)


@auth_app.command("doctor", help="检查 OAuth client、token 和 scopes。")
def auth_doctor(ctx: typer.Context) -> None:
    """检查认证状态。"""
    payload = credential_paths_payload()
    if not client_secret_path().exists():
        payload.update(
            status="missing_client_secret",
            next_step=missing_client_secret_message(client_secret_path()),
        )
        render_output(ctx, payload)
        return
    if not token_path().exists():
        payload.update(
            status="missing_token", next_step=missing_token_message(token_path())
        )
        render_output(ctx, payload)
        return
    credentials = load_credentials()
    payload.update(
        status="ok" if credentials.valid else "invalid",
        scopes=list(credentials.scopes or SCOPES),
        expiry=credentials.expiry.isoformat() if credentials.expiry else None,
    )
    render_output(ctx, payload)


@auth_app.command("login", help="执行 Desktop OAuth 登录并保存 Gmail token。")
def auth_login(
    ctx: typer.Context,
    open_browser: bool = typer.Option(
        True, "--open-browser/--no-open-browser", help="是否自动打开系统浏览器。"
    ),
) -> None:
    """执行完整 Gmail scopes 授权。"""
    secret = ensure_client_secret_exists()
    flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
    credentials = flow.run_local_server(
        port=0,
        open_browser=open_browser,
        access_type="offline",
        prompt="consent",
    )
    missing = missing_scopes(credentials)
    if missing:
        raise CliError("用户未授予必要 scope：" + ", ".join(missing))
    write_token(credentials)
    render_output(
        ctx,
        {
            "status": "ok",
            "token": str(token_path()),
            "scopes": list(credentials.scopes or SCOPES),
        },
    )


@auth_app.command("logout", help="删除本机 Gmail token，不删除共享 client secret。")
def auth_logout(ctx: typer.Context) -> None:
    """删除 Gmail token。"""
    path = token_path()
    existed = path.exists()
    if existed:
        path.unlink()
    render_output(ctx, {"status": "ok", "removed": existed, "token": str(path)})


@messages_app.command("search", help="使用 Gmail 搜索语法查找邮件。")
def messages_search(
    ctx: typer.Context,
    query: str = typer.Option("", "--query", "-q"),
    max_results: int = typer.Option(20, "--max-results", min=1, max=500),
    page_token: str | None = typer.Option(None, "--page-token"),
    include_spam_trash: bool = typer.Option(False, "--include-spam-trash"),
    details: bool = typer.Option(
        True, "--details/--no-details", help="同时读取常见邮件头与 snippet。"
    ),
) -> None:
    """搜索邮件并按需补充元数据。"""
    service = get_service()
    kwargs: dict[str, Any] = {
        "userId": "me",
        "q": query,
        "maxResults": max_results,
        "includeSpamTrash": include_spam_trash,
    }
    if page_token:
        kwargs["pageToken"] = page_token
    result = execute(service.users().messages().list(**kwargs))
    messages = result.get("messages", [])
    if details:
        messages = [
            normalize_message(
                execute(
                    service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=item["id"],
                        format="metadata",
                        metadataHeaders=list(DISPLAY_HEADERS),
                    )
                ),
                include_body=False,
            )
            for item in messages
        ]
    result["messages"] = messages
    render_output(ctx, result)


@messages_app.command("get", help="读取一封邮件及其正文、邮件头和附件元数据。")
def messages_get(
    ctx: typer.Context,
    message_id: str = typer.Option(..., "--message-id"),
    include_body: bool = typer.Option(True, "--body/--no-body"),
) -> None:
    """读取并标准化一封邮件。"""
    service = get_service()
    kwargs: dict[str, Any] = {
        "userId": "me",
        "id": message_id,
        "format": "full" if include_body else "metadata",
    }
    if not include_body:
        kwargs["metadataHeaders"] = list(DISPLAY_HEADERS)
    message = execute(service.users().messages().get(**kwargs))
    render_output(ctx, normalize_message(message, include_body=include_body))


@messages_app.command("modify", help="添加或移除邮件标签。")
def messages_modify(
    ctx: typer.Context,
    message_id: str = typer.Option(..., "--message-id"),
    add_label_id: list[str] | None = typer.Option(None, "--add-label-id"),
    remove_label_id: list[str] | None = typer.Option(None, "--remove-label-id"),
) -> None:
    """修改一封邮件的标签。"""
    if not add_label_id and not remove_label_id:
        raise CliError("至少提供一个 --add-label-id 或 --remove-label-id。")
    service = get_service()
    result = execute(
        service.users()
        .messages()
        .modify(
            userId="me",
            id=message_id,
            body={
                "addLabelIds": add_label_id or [],
                "removeLabelIds": remove_label_id or [],
            },
        )
    )
    render_output(ctx, normalize_message(result, include_body=False))


@threads_app.command("get", help="读取一个邮件线程中的所有邮件。")
def threads_get(
    ctx: typer.Context,
    thread_id: str = typer.Option(..., "--thread-id"),
    include_body: bool = typer.Option(True, "--body/--no-body"),
) -> None:
    """读取并标准化邮件线程。"""
    service = get_service()
    kwargs: dict[str, Any] = {
        "userId": "me",
        "id": thread_id,
        "format": "full" if include_body else "metadata",
    }
    if not include_body:
        kwargs["metadataHeaders"] = list(DISPLAY_HEADERS)
    thread = execute(service.users().threads().get(**kwargs))
    render_output(
        ctx,
        {
            "id": thread.get("id"),
            "historyId": thread.get("historyId"),
            "messages": [
                normalize_message(message, include_body=include_body)
                for message in thread.get("messages", [])
            ],
        },
    )


@threads_app.command("modify", help="为线程内现有邮件添加或移除标签。")
def threads_modify(
    ctx: typer.Context,
    thread_id: str = typer.Option(..., "--thread-id"),
    add_label_id: list[str] | None = typer.Option(None, "--add-label-id"),
    remove_label_id: list[str] | None = typer.Option(None, "--remove-label-id"),
) -> None:
    """修改邮件线程标签。"""
    if not add_label_id and not remove_label_id:
        raise CliError("至少提供一个 --add-label-id 或 --remove-label-id。")
    service = get_service()
    result = execute(
        service.users()
        .threads()
        .modify(
            userId="me",
            id=thread_id,
            body={
                "addLabelIds": add_label_id or [],
                "removeLabelIds": remove_label_id or [],
            },
        )
    )
    render_output(ctx, result)


@labels_app.command("list", help="列出系统标签和用户标签。")
def labels_list(ctx: typer.Context) -> None:
    """列出标签。"""
    service = get_service()
    render_output(ctx, execute(service.users().labels().list(userId="me")))


@labels_app.command("create", help="创建用户标签。")
def labels_create(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name"),
    label_list_visibility: str = typer.Option("labelShow", "--label-list-visibility"),
    message_list_visibility: str = typer.Option("show", "--message-list-visibility"),
) -> None:
    """创建用户标签。"""
    service = get_service()
    result = execute(
        service.users()
        .labels()
        .create(
            userId="me",
            body={
                "name": name,
                "labelListVisibility": label_list_visibility,
                "messageListVisibility": message_list_visibility,
            },
        )
    )
    render_output(ctx, result)


@labels_app.command("update", help="更新用户标签名称或可见性。")
def labels_update(
    ctx: typer.Context,
    label_id: str = typer.Option(..., "--label-id"),
    name: str | None = typer.Option(None, "--name"),
    label_list_visibility: str | None = typer.Option(None, "--label-list-visibility"),
    message_list_visibility: str | None = typer.Option(
        None, "--message-list-visibility"
    ),
    confirm_update: bool = typer.Option(False, "--confirm-update"),
) -> None:
    """局部更新用户标签，保留未指定字段及现有标签 ID。"""
    require_confirmation(confirm_update, "--confirm-update", "更新用户标签")
    body = {
        key: value
        for key, value in {
            "name": name,
            "labelListVisibility": label_list_visibility,
            "messageListVisibility": message_list_visibility,
        }.items()
        if value is not None
    }
    if not body:
        raise CliError("至少提供 --name 或一个可见性参数。")
    if "name" in body and not body["name"].strip():
        raise CliError("--name 不能为空。")
    service = get_service()
    result = execute(
        service.users().labels().patch(userId="me", id=label_id, body=body)
    )
    render_output(ctx, result)


@drafts_app.command("list", help="列出草稿，可使用 Gmail 搜索语法过滤。")
def drafts_list(
    ctx: typer.Context,
    query: str = typer.Option("", "--query", "-q"),
    max_results: int = typer.Option(20, "--max-results", min=1, max=500),
    page_token: str | None = typer.Option(None, "--page-token"),
    details: bool = typer.Option(
        True, "--details/--no-details", help="同时读取草稿邮件头与 snippet。"
    ),
) -> None:
    """列出草稿并按需补充元数据。"""
    service = get_service()
    kwargs: dict[str, Any] = {
        "userId": "me",
        "q": query,
        "maxResults": max_results,
    }
    if page_token:
        kwargs["pageToken"] = page_token
    result = execute(service.users().drafts().list(**kwargs))
    drafts = result.get("drafts", [])
    if details:
        detailed = []
        for item in drafts:
            draft = execute(
                service.users()
                .drafts()
                .get(
                    userId="me",
                    id=item["id"],
                    format="metadata",
                )
            )
            detailed.append(
                {
                    "id": draft.get("id"),
                    "message": normalize_message(
                        draft.get("message", {}), include_body=False
                    ),
                }
            )
        drafts = detailed
    result["drafts"] = drafts
    render_output(ctx, result)


@drafts_app.command("get", help="读取一个草稿。")
def drafts_get(
    ctx: typer.Context,
    draft_id: str = typer.Option(..., "--draft-id"),
    include_body: bool = typer.Option(True, "--body/--no-body"),
) -> None:
    """读取并标准化草稿。"""
    service = get_service()
    draft = execute(
        service.users()
        .drafts()
        .get(
            userId="me",
            id=draft_id,
            format="full" if include_body else "metadata",
        )
    )
    render_output(
        ctx,
        {
            "id": draft.get("id"),
            "message": normalize_message(
                draft.get("message", {}), include_body=include_body
            ),
        },
    )


@attachments_app.command("download", help="下载 messages get 返回的附件。")
def attachments_download(
    ctx: typer.Context,
    message_id: str = typer.Option(..., "--message-id"),
    attachment_id: str = typer.Option(..., "--attachment-id"),
    output: Path = typer.Option(..., "--output"),
    overwrite: bool = typer.Option(False, "--overwrite"),
) -> None:
    """下载附件到明确的本地文件。"""
    service = get_service()
    result = execute(
        service.users()
        .messages()
        .attachments()
        .get(userId="me", messageId=message_id, id=attachment_id)
    )
    data = decode_base64url(str(result.get("data", "")))
    write_download(data, output, overwrite=overwrite)
    render_output(
        ctx,
        {
            "status": "ok",
            "messageId": message_id,
            "attachmentId": attachment_id,
            "output": str(output.expanduser()),
            "size": len(data),
        },
    )


def compose_options(function: Any) -> Any:
    """保留命令签名，便于组合相关命令保持一致。"""
    return function


@drafts_app.command("create", help="创建邮件草稿，不会发送。")
@compose_options
def drafts_create(
    ctx: typer.Context,
    to: list[str] | None = typer.Option(None, "--to"),
    cc: list[str] | None = typer.Option(None, "--cc"),
    bcc: list[str] | None = typer.Option(None, "--bcc"),
    subject: str = typer.Option("", "--subject"),
    body: str | None = typer.Option(None, "--body"),
    body_file: Path | None = typer.Option(None, "--body-file"),
    html_body: str | None = typer.Option(None, "--html-body"),
    html_body_file: Path | None = typer.Option(None, "--html-body-file"),
    attachment: list[Path] | None = typer.Option(None, "--attachment"),
    from_address: str | None = typer.Option(None, "--from"),
    thread_id: str | None = typer.Option(None, "--thread-id"),
    in_reply_to: str | None = typer.Option(None, "--in-reply-to"),
    references: str | None = typer.Option(None, "--references"),
) -> None:
    """创建草稿。"""
    service = get_service()
    resource = compose_resource(
        service,
        from_address=from_address,
        to=to,
        cc=cc,
        bcc=bcc,
        subject=subject,
        body=body,
        body_file=body_file,
        html_body=html_body,
        html_body_file=html_body_file,
        attachment=attachment,
        thread_id=thread_id,
        in_reply_to=in_reply_to,
        references=references,
    )
    result = execute(
        service.users().drafts().create(userId="me", body={"message": resource})
    )
    render_output(ctx, result)


@drafts_app.command("update", help="完整替换已有草稿内容，不会发送。")
@compose_options
def drafts_update(
    ctx: typer.Context,
    draft_id: str = typer.Option(..., "--draft-id"),
    to: list[str] | None = typer.Option(None, "--to"),
    cc: list[str] | None = typer.Option(None, "--cc"),
    bcc: list[str] | None = typer.Option(None, "--bcc"),
    subject: str = typer.Option("", "--subject"),
    body: str | None = typer.Option(None, "--body"),
    body_file: Path | None = typer.Option(None, "--body-file"),
    html_body: str | None = typer.Option(None, "--html-body"),
    html_body_file: Path | None = typer.Option(None, "--html-body-file"),
    attachment: list[Path] | None = typer.Option(None, "--attachment"),
    from_address: str | None = typer.Option(None, "--from"),
    thread_id: str | None = typer.Option(None, "--thread-id"),
    in_reply_to: str | None = typer.Option(None, "--in-reply-to"),
    references: str | None = typer.Option(None, "--references"),
) -> None:
    """完整替换草稿内容。"""
    service = get_service()
    resource = compose_resource(
        service,
        from_address=from_address,
        to=to,
        cc=cc,
        bcc=bcc,
        subject=subject,
        body=body,
        body_file=body_file,
        html_body=html_body,
        html_body_file=html_body_file,
        attachment=attachment,
        thread_id=thread_id,
        in_reply_to=in_reply_to,
        references=references,
    )
    result = execute(
        service.users()
        .drafts()
        .update(
            userId="me",
            id=draft_id,
            body={"id": draft_id, "message": resource},
        )
    )
    render_output(ctx, result)


@send_app.command("message", help="构造并发送一封新邮件。")
@compose_options
def send_message(
    ctx: typer.Context,
    confirm_send: bool = typer.Option(False, "--confirm-send"),
    to: list[str] | None = typer.Option(None, "--to"),
    cc: list[str] | None = typer.Option(None, "--cc"),
    bcc: list[str] | None = typer.Option(None, "--bcc"),
    subject: str = typer.Option("", "--subject"),
    body: str | None = typer.Option(None, "--body"),
    body_file: Path | None = typer.Option(None, "--body-file"),
    html_body: str | None = typer.Option(None, "--html-body"),
    html_body_file: Path | None = typer.Option(None, "--html-body-file"),
    attachment: list[Path] | None = typer.Option(None, "--attachment"),
    from_address: str | None = typer.Option(None, "--from"),
    thread_id: str | None = typer.Option(None, "--thread-id"),
    in_reply_to: str | None = typer.Option(None, "--in-reply-to"),
    references: str | None = typer.Option(None, "--references"),
) -> None:
    """发送新邮件。"""
    require_confirmation(confirm_send, "--confirm-send", "发送邮件")
    service = get_service()
    resource = compose_resource(
        service,
        from_address=from_address,
        to=to,
        cc=cc,
        bcc=bcc,
        subject=subject,
        body=body,
        body_file=body_file,
        html_body=html_body,
        html_body_file=html_body_file,
        attachment=attachment,
        thread_id=thread_id,
        in_reply_to=in_reply_to,
        references=references,
    )
    result = execute(service.users().messages().send(userId="me", body=resource))
    render_output(ctx, result)


@send_app.command("draft", help="发送一个已有草稿。")
def send_draft(
    ctx: typer.Context,
    draft_id: str = typer.Option(..., "--draft-id"),
    confirm_send: bool = typer.Option(False, "--confirm-send"),
) -> None:
    """发送已有草稿。"""
    require_confirmation(confirm_send, "--confirm-send", "发送草稿")
    service = get_service()
    result = execute(service.users().drafts().send(userId="me", body={"id": draft_id}))
    render_output(ctx, result)


@filters_app.command("list", help="列出 Gmail 过滤规则。")
def filters_list(ctx: typer.Context) -> None:
    """列出过滤规则。"""
    service = get_service()
    render_output(ctx, execute(service.users().settings().filters().list(userId="me")))


@filters_app.command("get", help="读取一个 Gmail 过滤规则。")
def filters_get(
    ctx: typer.Context,
    filter_id: str = typer.Option(..., "--filter-id"),
) -> None:
    """读取过滤规则。"""
    service = get_service()
    render_output(
        ctx,
        execute(service.users().settings().filters().get(userId="me", id=filter_id)),
    )


@filters_app.command("create", help="创建 Gmail 过滤规则。")
def filters_create(
    ctx: typer.Context,
    filter_json: str = typer.Option(..., "--filter-json"),
    confirm_create: bool = typer.Option(False, "--confirm-create"),
) -> None:
    """校验并创建过滤规则。"""
    require_confirmation(confirm_create, "--confirm-create", "创建过滤规则")
    body = validate_filter(load_json_arg(filter_json, "--filter-json"))
    service = get_service()
    result = execute(
        service.users().settings().filters().create(userId="me", body=body)
    )
    render_output(ctx, result)


@filters_app.command("delete", help="永久删除一条过滤规则。")
def filters_delete(
    ctx: typer.Context,
    filter_id: str = typer.Option(..., "--filter-id"),
    confirm_delete: bool = typer.Option(False, "--confirm-delete"),
) -> None:
    """删除过滤规则。"""
    require_confirmation(confirm_delete, "--confirm-delete", "删除过滤规则")
    service = get_service()
    execute(service.users().settings().filters().delete(userId="me", id=filter_id))
    render_output(ctx, {"status": "ok", "deleted": filter_id})


app.add_typer(auth_app, name="auth")
app.add_typer(messages_app, name="messages")
app.add_typer(threads_app, name="threads")
app.add_typer(labels_app, name="labels")
app.add_typer(drafts_app, name="drafts")
app.add_typer(send_app, name="send")
app.add_typer(filters_app, name="filters")
app.add_typer(attachments_app, name="attachments")


def run() -> None:
    """运行 CLI 并以简洁方式展示预期错误。"""
    try:
        app()
    except CliError as exc:
        console.print(f"[red]错误：[/red]{exc}", markup=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    run()
