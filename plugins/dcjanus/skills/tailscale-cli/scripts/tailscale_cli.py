#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.15"
# dependencies = [
#     "httpx2>=2.16.0",
#     "typer>=0.27.3",
# ]
# ///

"""通过 Tailscale 官方 API 管理 tailnet 策略，保留原始 HuJSON。"""

from __future__ import annotations

import difflib
import json
import os
import subprocess
import tomllib
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

import httpx2
import typer

API_BASE = "https://api.tailscale.com/api/v2"
app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
policy_app = typer.Typer(no_args_is_help=True, help="读取、校验、预览和发布整份策略。")
app.add_typer(policy_app, name="policy")
api_app = typer.Typer(
    no_args_is_help=True,
    help="发现并调用官方只读 API，覆盖设备、用户、DNS、设置、日志等。",
)
app.add_typer(api_app, name="api")
auth_app = typer.Typer(no_args_is_help=True, help="检查配置、凭据读取和策略读取权限。")
app.add_typer(auth_app, name="auth")
READ_API = json.loads(
    (Path(__file__).resolve().parents[1] / "references/read-api.json").read_text(
        encoding="utf-8"
    )
)
READ_OPERATIONS = READ_API["operations"]
ReadOperation = Enum(
    "ReadOperation", {name: name for name in READ_OPERATIONS}, type=str
)


class OperationError(Exception):
    """可向调用方报告的操作错误。"""


class PreviewType(str, Enum):
    """官方预览接口支持的资源类型。"""

    user = "user"
    ipport = "ipport"


@dataclass
class State:
    """全局选项。"""

    config: Path
    tailnet: str | None
    json_output: bool


def credentials_from_op(item: str, vault: str | None) -> dict[str, str]:
    """一次读取指定条目，只在内存使用凭据，不输出 op 的敏感诊断。"""
    command = ["op", "item", "get", "--format", "json", "--reveal"]
    if vault:
        command.extend(["--vault", vault])
    command.extend(["--", item])
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
            # 保留当前 shell 的终端输入上下文，供 1Password 桌面集成复用授权。
            stdin=None,
        )
    except FileNotFoundError:
        raise OperationError("未找到 op，请安装 1Password CLI 并加入 PATH。") from None
    except OSError, subprocess.TimeoutExpired:
        raise OperationError(
            "1Password 读取未完成。请解锁桌面应用，在设置 → 开发者开启 "
            "Integrate with 1Password CLI，在本机终端运行 op signin 并批准授权；"
            "若终端成功而 Agent 失败，需为 Agent 所在应用单独批准访问。"
        ) from None
    if result.returncode:
        raise OperationError(
            "1Password 条目读取失败。请在本机终端运行 op signin 并批准授权，"
            "再核对条目 ID/名称和保险库；不会回退到明文凭据。"
        )
    try:
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict) or not isinstance(payload.get("fields"), list):
            raise TypeError
        credentials = {}
        for field in payload["fields"]:
            label = field.get("label")
            if label not in {"api_token", "client_id", "client_secret"}:
                continue
            value = field.get("value")
            if label in credentials or not isinstance(value, str) or not value.strip():
                raise ValueError
            credentials[label] = value
    except ValueError, AttributeError, TypeError:
        raise OperationError(
            "1Password 条目格式无效，请检查唯一且非空的 client_id、client_secret 或 api_token 字段。"
        ) from None
    return credentials


def emit(state: State, value: Any, *, error: bool = False) -> None:
    """输出结构化结果或便于阅读的文本。"""
    if state.json_output:
        typer.echo(json.dumps(value, ensure_ascii=False), err=error)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in {"policy", "diff"}:
                typer.echo(item, nl=not str(item).endswith("\n"), err=error)
            else:
                typer.echo(f"{key}: {json.dumps(item, ensure_ascii=False)}", err=error)
    else:
        typer.echo(json.dumps(value, ensure_ascii=False, indent=2), err=error)


def default_config() -> Path:
    """遵循 XDG 配置目录。"""
    return (
        Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        / "tailscale-cli/config.toml"
    )


@app.callback()
def configure(
    ctx: typer.Context,
    config: Annotated[
        Path | None,
        typer.Option(
            "--config",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="TOML 配置路径；默认 $XDG_CONFIG_HOME/tailscale-cli/config.toml（未设置时 ~/.config）。",
        ),
    ] = None,
    tailnet: Annotated[
        str | None,
        typer.Option(
            "--tailnet",
            envvar="TS_TAILNET",
            help="Tailnet ID 或名称；优先级：选项、TS_TAILNET、配置 tailnet。",
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="stdout 输出 JSON 结果，stderr 输出 JSON 错误。"),
    ] = False,
) -> None:
    """管理 Tailscale 策略和查询后台资源；凭据支持环境变量、TOML 或 op_item 指定的 1Password 条目。"""
    ctx.obj = State(config or default_config(), tailnet, json_output)


class Client:
    """固定官方 API 地址，不重试写请求或输出凭据。"""

    def __init__(self, state: State):
        settings = {}
        if state.config.exists():
            try:
                settings = tomllib.loads(state.config.read_text(encoding="utf-8"))
            except OSError, ValueError:
                raise OperationError(
                    "无法读取 TOML 配置，请检查文件格式与权限。"
                ) from None
        allowed = {
            "tailnet",
            "api_token",
            "client_id",
            "client_secret",
            "op_item",
            "op_vault",
        }
        if settings.keys() - allowed or any(
            not isinstance(v, str) or not v.strip() for v in settings.values()
        ):
            raise OperationError(
                "配置仅支持非空字符串 tailnet、api_token、client_id、client_secret、op_item、op_vault。"
            )
        self.tailnet = state.tailnet or settings.get("tailnet")
        if not self.tailnet or not self.tailnet.strip() or self.tailnet == "-":
            raise OperationError(
                "请通过 --tailnet、TS_TAILNET 或配置指定明确的 tailnet，不能使用 '-'。"
            )
        self.path = f"/tailnet/{quote(self.tailnet, safe='')}/acl"
        env_credentials = {
            "api_token": os.environ.get("TS_API_KEY"),
            "client_id": os.environ.get("TS_CLIENT_ID"),
            "client_secret": os.environ.get("TS_CLIENT_SECRET"),
        }
        credentials = (
            env_credentials
            if any(v is not None for v in env_credentials.values())
            else settings
        )
        if credentials.get("op_vault") and not credentials.get("op_item"):
            raise OperationError("op_vault 必须与 op_item 一起配置。")
        if credentials.get("op_item"):
            if any(
                credentials.get(key)
                for key in ("api_token", "client_id", "client_secret")
            ):
                raise OperationError("op_item 与 TOML 明文凭据互斥，请仅保留条目引用。")
            credentials = credentials_from_op(
                credentials["op_item"], credentials.get("op_vault")
            )
        token = credentials.get("api_token")
        client_id = credentials.get("client_id")
        secret = credentials.get("client_secret")
        if token and (client_id or secret):
            raise OperationError("API token 与 OAuth 凭据互斥，请仅配置一种认证方式。")
        if not token and not (client_id and secret):
            raise OperationError(
                "请配置 op_item，或设置 TS_API_KEY，或同时设置 TS_CLIENT_ID 和 TS_CLIENT_SECRET；1Password 条目使用同名小写字段 api_token 或 client_id、client_secret。"
            )
        self.http = httpx2.Client(timeout=30, follow_redirects=False)
        try:
            if not token:
                response = self.request(
                    "POST",
                    "/oauth/token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": client_id,
                        "client_secret": secret,
                    },
                )
                payload = response.json()
                token = (
                    payload.get("access_token") if isinstance(payload, dict) else None
                )
                if not isinstance(token, str) or not token:
                    raise OperationError("OAuth 响应缺少 access_token。")
            self.http.headers["Authorization"] = f"Bearer {token}"
        except Exception:
            self.http.close()
            raise

    def request(self, method: str, path: str, **kwargs) -> httpx2.Response:
        """处理 HTTP 错误，保留策略错误详情但不回显认证响应。"""
        try:
            response = self.http.request(method, API_BASE + path, **kwargs)
        except httpx2.RequestError:
            raise OperationError(
                "网络请求失败；若已尝试发布，结果未知，请先重新读取策略再判断，勿盲目重试。"
            ) from None
        if not response.is_success:
            if response.status_code == 412:
                raise OperationError("策略已变化（HTTP 412），请重新读取并合并改动。")
            if path == "/oauth/token" or response.status_code in {401, 403}:
                raise OperationError(
                    f"认证或权限不足（HTTP {response.status_code}），请检查凭据和 scopes。"
                )
            raise OperationError(
                f"Tailscale API HTTP {response.status_code}: {response.text}"
            )
        return response

    def get(self) -> tuple[bytes, str]:
        """读取原始 HuJSON 和强 ETag。"""
        response = self.request(
            "GET", self.path, headers={"Accept": "application/hujson"}
        )
        etag = response.headers.get("ETag", "")
        if not etag:
            raise OperationError("策略响应缺少 ETag，无法安全发布。")
        return response.content, etag

    def validate(self, content: bytes) -> dict:
        """识别 HTTP 200 内的测试失败；警告保留给调用方。"""
        response = self.request(
            "POST",
            self.path + "/validate",
            content=content,
            headers={"Content-Type": "application/hujson"},
        )
        result = response.json() if response.content.strip() else {}
        if not isinstance(result, dict):
            raise OperationError("无法识别策略校验响应。")
        errors = result.get("errors") or any(
            item.get("errors") for item in result.get("data", []) or []
        )
        message = result.get("message", "")
        if errors or (message and message != "warning(s) found"):
            raise OperationError(
                "策略校验失败：" + json.dumps(result, ensure_ascii=False)
            )
        return result


@dataclass(frozen=True)
class Assignment:
    """命令行中的具名 API 参数。"""

    name: str
    value: str


def parse_assignment(value: str) -> Assignment:
    """解析 NAME=VALUE，保留值中的等号。"""
    name, separator, content = value.partition("=")
    if not separator or not name or not content:
        raise ValueError("使用 NAME=VALUE，名称和值不能为空。")
    return Assignment(name, content)


def validate_api_value(parameter: dict, value: str) -> None:
    """校验目录中声明的枚举和标量类型，剩余语义由服务端判断。"""
    name = parameter["name"]
    if "enum" in parameter and value not in parameter["enum"]:
        raise typer.BadParameter(f"{name} 必须为 {', '.join(parameter['enum'])}。")
    if parameter["type"] == "boolean" and value not in {"true", "false"}:
        raise typer.BadParameter(f"{name} 必须为 true 或 false。")
    if parameter["type"] == "integer":
        try:
            number = int(value)
        except ValueError:
            raise typer.BadParameter(f"{name} 必须为整数。") from None
        if number < parameter.get("minimum", number) or number > parameter.get(
            "maximum", number
        ):
            raise typer.BadParameter(f"{name} 超出范围；请查看 api describe。")


def prepare_api_request(
    operation: dict, parameters: list[Assignment], query: list[Assignment]
) -> tuple[str, list[tuple[str, str]]]:
    """按只读目录校验参数；tailnet 始终来自全局配置。"""
    template = operation["path"]
    for location, supplied in (("path", parameters), ("query", query)):
        definitions = {
            p["name"]: p
            for p in operation["parameters"]
            if p["in"] == location and p["name"] != "tailnet"
        }
        filters = operation.get("device_filters", []) if location == "query" else []
        seen = set()
        for pair in supplied:
            if pair.name not in definitions and pair.name not in filters:
                raise typer.BadParameter(
                    f"不支持的 {location} 参数 {pair.name}；用 api describe 查看，tailnet 请使用全局 --tailnet。"
                )
            definition = definitions.get(pair.name)
            if (
                pair.name in seen
                and pair.name not in filters
                and definition["type"] != "array"
            ):
                raise typer.BadParameter(f"{pair.name} 不能重复。")
            if definition:
                validate_api_value(definition, pair.value)
            seen.add(pair.name)
            if location == "path":
                if pair.value in {".", ".."}:
                    raise typer.BadParameter("路径参数不能为 . 或 ..。")
                template = template.replace(
                    "{" + pair.name + "}", quote(pair.value, safe="")
                )
        missing = {
            name for name, definition in definitions.items() if definition["required"]
        } - seen
        if missing:
            raise typer.BadParameter(
                f"缺少 {location} 参数：{', '.join(sorted(missing))}；用 api describe 查看。"
            )
    return template, [(pair.name, pair.value) for pair in query]


@api_app.command("list")
def list_api(
    ctx: typer.Context,
    search: Annotated[
        str | None,
        typer.Option(
            "--search", help="按接口名称、摘要或路径筛选；不联网、不读取凭据。"
        ),
    ] = None,
) -> None:
    """列出可用的官方 GET 接口；不包含新增的写操作。"""
    operations = [
        {"operation": name, "summary": operation["summary"], "path": operation["path"]}
        for name, operation in READ_OPERATIONS.items()
    ]
    if search:
        operations = [
            operation
            for operation in operations
            if search.casefold() in json.dumps(operation).casefold()
        ]
    emit(ctx.obj, operations)


@api_app.command("describe")
def describe_api(
    ctx: typer.Context,
    operation: Annotated[
        ReadOperation,
        typer.Argument(
            metavar="OPERATION",
            help="api list 中的官方 operation ID；不联网、不读取凭据。",
        ),
    ],
) -> None:
    """查看接口路径、必填参数、类型、枚举与查询说明。"""
    emit(
        ctx.obj,
        {
            "operation": operation.value,
            "method": "GET",
            **READ_OPERATIONS[operation.value],
        },
    )


@api_app.command("get")
def get_api(
    ctx: typer.Context,
    operation: Annotated[
        ReadOperation,
        typer.Argument(
            metavar="OPERATION",
            help="api list 中的官方 operation ID；仅允许目录内 GET 接口。",
        ),
    ],
    parameter: Annotated[
        list[Assignment] | None,
        typer.Option(
            "--param",
            parser=parse_assignment,
            metavar="NAME=VALUE",
            help="路径参数，可重复指定不同名称；tailnet 自动取全局配置。",
        ),
    ] = None,
    query: Annotated[
        list[Assignment] | None,
        typer.Option(
            "--query",
            parser=parse_assignment,
            metavar="NAME=VALUE",
            help="查询参数，可重复；数组与设备过滤器允许同名多值，布尔值为 true/false。分页参数需显式传入。",
        ),
    ] = None,
) -> None:
    """查询一页结果，保留原始 JSON 和分页信息；先用 api describe 查看参数。"""
    path, query_pairs = prepare_api_request(
        READ_OPERATIONS[operation.value], parameter or [], query or []
    )
    with connection(ctx) as client:
        path = path.replace("{tailnet}", quote(client.tailnet, safe=""))
        headers = (
            {}
            if operation.value == "getPolicyFile" and ("details", "true") in query_pairs
            else {"Accept": "application/json"}
        )
        response = client.request("GET", path, params=query_pairs, headers=headers)
        emit(ctx.obj, response.json())


@contextmanager
def connection(ctx: typer.Context):
    """统一关闭连接并将预期错误转为 CLI 失败。"""
    client = None
    try:
        client = Client(ctx.obj)
        yield client
    except FileExistsError:
        emit(
            ctx.obj,
            {"ok": False, "error": "保存目标已存在，请选择新文件，避免覆盖本地编辑。"},
            error=True,
        )
        raise typer.Exit(1) from None
    except (OperationError, OSError, ValueError) as exc:
        # 不输出 JSON/TOML 解码异常中的输入正文，以免认证响应泄露。
        message = (
            str(exc)
            if isinstance(exc, OperationError)
            else "无法读取文件或解析 API 响应，请检查输入与服务状态。"
        )
        emit(ctx.obj, {"ok": False, "error": message}, error=True)
        raise typer.Exit(1) from None
    finally:
        if client:
            client.http.close()


PolicyFile = Annotated[
    Path,
    typer.Argument(
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="完整 JSON/HuJSON 策略文件；保留注释和尾逗号，原样发送。",
    ),
]


@auth_app.command("check")
def check_auth(ctx: typer.Context) -> None:
    """读取配置及凭据，并用只读 API 验证策略权限；不展示凭据或策略正文。"""
    with connection(ctx) as client:
        client.get()
        emit(ctx.obj, {"ok": True, "tailnet": client.tailnet, "policy_readable": True})


def read_policy(path: Path) -> bytes:
    """先检查本地文件，避免空策略触发请求。"""
    content = path.read_bytes()
    if not content.strip():
        raise OperationError("策略文件为空。")
    content.decode("utf-8")
    return content


@policy_app.command("get")
def get_policy(
    ctx: typer.Context,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="将原始 HuJSON 保存到新文件；不覆盖已有文件。结果同时包含 ETag。",
        ),
    ] = None,
) -> None:
    """读取线上策略及 ETag，供编辑和后续发布使用。"""
    with connection(ctx) as client:
        content, etag = client.get()
        result = {"tailnet": client.tailnet, "etag": etag}
        if output:
            with output.open("xb") as stream:
                stream.write(content)
            result["output"] = str(output)
        else:
            result["policy"] = content.decode("utf-8")
        emit(ctx.obj, result)


@policy_app.command("validate")
def validate_policy(ctx: typer.Context, file: PolicyFile) -> None:
    """在服务端校验候选策略及其中测试，不修改线上策略。"""
    with connection(ctx) as client:
        result = client.validate(read_policy(file))
        emit(ctx.obj, {"ok": True, "validation": result})


@policy_app.command("preview")
def preview_policy(
    ctx: typer.Context,
    file: PolicyFile,
    resource_type: Annotated[
        PreviewType,
        typer.Option("--type", help="user：有已注册设备的用户；ipport：目标 IP:端口。"),
    ],
    preview_for: Annotated[
        str,
        typer.Option(
            "--for",
            help="与 --type 对应的用户邮箱或 IP:端口，如 user@example.com 或 100.101.102.103:22。",
        ),
    ],
) -> None:
    """预览候选策略对指定资源的匹配规则，不保存策略。"""
    with connection(ctx) as client:
        response = client.request(
            "POST",
            client.path + "/preview",
            content=read_policy(file),
            headers={"Content-Type": "application/hujson"},
            params={"type": resource_type.value, "previewFor": preview_for},
        )
        emit(ctx.obj, response.json())


def parse_etag(value: str) -> str:
    """只接受 GET 返回的单个强 ETag，拒绝绕过版本检查。"""
    if (
        len(value) < 3
        or not value.startswith('"')
        or not value.endswith('"')
        or any(c in value[1:-1] for c in '\r\n"')
    ):
        raise ValueError(
            "必须传入 GET 返回的带双引号 ETag；不支持 *、弱 ETag 或多个 ETag。"
        )
    return value


@policy_app.command("apply")
def apply_policy(
    ctx: typer.Context,
    file: PolicyFile,
    if_match: Annotated[
        str,
        typer.Option(
            "--if-match",
            parser=parse_etag,
            metavar="ETAG",
            help="编辑前读取的 ETag，保留双引号；必须与线上一致。",
        ),
    ],
    execute: Annotated[
        bool,
        typer.Option(
            "--execute", help="实际发布整份策略并回读；不传时仅显示 diff 和校验结果。"
        ),
    ] = False,
) -> None:
    """默认 dry-run；显式执行时通过 If-Match 防止覆盖他人改动。"""
    with connection(ctx) as client:
        candidate = read_policy(file)
        current, etag = client.get()
        if etag != if_match:
            raise OperationError("线上 ETag 与编辑基准不一致，请重新读取并合并改动。")
        diff = "".join(
            difflib.unified_diff(
                current.decode().splitlines(keepends=True),
                candidate.decode().splitlines(keepends=True),
                fromfile="online",
                tofile=str(file),
            )
        )
        validation = client.validate(candidate)
        result = {
            "tailnet": client.tailnet,
            "etag": etag,
            "diff": diff,
            "validation": validation,
            "applied": False,
        }
        if execute and candidate != current:
            updated = client.request(
                "POST",
                client.path,
                content=candidate,
                headers={
                    "Content-Type": "application/hujson",
                    "Accept": "application/hujson",
                    "If-Match": if_match,
                },
            )
            try:
                actual, actual_etag = client.get()
            except OperationError as exc:
                raise OperationError(f"发布请求已成功，但回读未确认：{exc}") from None
            expected_etag = updated.headers.get("ETag")
            if (expected_etag and expected_etag != actual_etag) or (
                not expected_etag and updated.content != actual
            ):
                raise OperationError(
                    "发布请求已成功，但回读与发布结果不一致；请重新读取线上策略，勿盲目重试。"
                )
            result.update(applied=True, etag=actual_etag, verified=True)
        emit(ctx.obj, result)


if __name__ == "__main__":
    app()
