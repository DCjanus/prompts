#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "openai-codex>=0.144.4",
#     "pydantic>=2.13.4",
#     "pyyaml>=6.0.3",
#     "typer>=0.27.1",
# ]
# ///

"""读取结构化 YAML，安全生成并创建 Git commit。"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Annotated, Any, Self

import typer
import yaml
from openai_codex import CodexConfig
from openai_codex.client import CodexClient
from openai_codex.errors import CodexError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

AGENT_NAME = "Codex"
CONVENTIONAL_SUBJECT = re.compile(r"^[a-z][a-z0-9-]*(?:\([^\r\n)]+\))?!?: [^\r\n]+$")
BREAKING_SUBJECT = re.compile(r"^[a-z][a-z0-9-]*(?:\([^\r\n)]+\))?!: .+$")
BREAKING_PREFIX = "BREAKING CHANGE:"
TRAILER_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9-]*$")
app = typer.Typer(add_completion=False, help=__doc__)


class CommitError(RuntimeError):
    """提交规范或 Git 操作失败。"""


class CommitValidationError(CommitError):
    """渲染后的提交信息不符合约定。"""


def parsed_trailers(message: str) -> list[str]:
    """使用 Git 自身的解析器返回结构化 trailers。"""

    try:
        result = subprocess.run(
            ["git", "interpret-trailers", "--parse"],
            input=message,
            text=True,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CommitValidationError(f"failed to parse Git trailers: {exc}") from exc
    return result.stdout.splitlines()


def validate_message(message: str, assisted_by: str | None) -> None:
    """验证 breaking 标记与可选的 Assisted-by trailer。"""

    lines = message.rstrip("\n").splitlines()
    if not lines:
        raise CommitValidationError("commit message is empty")

    title_is_breaking = BREAKING_SUBJECT.fullmatch(lines[0]) is not None
    breaking_footers = [line for line in lines[1:] if line.startswith(BREAKING_PREFIX)]
    if title_is_breaking and len(breaking_footers) != 1:
        raise CommitValidationError(
            "a breaking title must contain exactly one BREAKING CHANGE footer"
        )
    if not title_is_breaking and breaking_footers:
        raise CommitValidationError("a BREAKING CHANGE footer requires ! in the title")
    if breaking_footers:
        footer_value = breaking_footers[0].removeprefix(BREAKING_PREFIX).strip()
        if not footer_value or footer_value.endswith(":"):
            raise CommitValidationError("malformed BREAKING CHANGE footer")

    assisted_by_trailers = [
        trailer
        for trailer in parsed_trailers(message)
        if trailer.lower().startswith("assisted-by:")
    ]
    if assisted_by is None:
        if assisted_by_trailers:
            raise CommitValidationError(
                "Assisted-by must be absent when validation skips it"
            )
        return

    expected = f"Assisted-by: {assisted_by}"
    occurrences = assisted_by_trailers.count(expected)
    if occurrences != 1 or len(assisted_by_trailers) != 1:
        raise CommitValidationError(
            f"expected exactly one parsed trailer {expected!r}, got {occurrences}"
        )


def reject_literal_newlines(value: Any, location: str = "root") -> None:
    """递归拒绝 YAML 字符串中的字面量反斜杠 n。"""

    if isinstance(value, str):
        if "\\n" in value:
            raise ValueError(f"{location} contains a literal \\n; use YAML structure")
        return
    if isinstance(value, dict):
        for key, child in value.items():
            reject_literal_newlines(child, f"{location}.{key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            reject_literal_newlines(child, f"{location}[{index}]")


class StrictModel(BaseModel):
    """拒绝未声明字段的 YAML 模型。"""

    model_config = ConfigDict(extra="forbid")


class BreakingChange(StrictModel):
    """破坏性变更的影响和迁移方式。"""

    impact: str = Field(min_length=1)
    migration: str = Field(min_length=1)


class Trailer(StrictModel):
    """一个普通 Git trailer。"""

    key: str = Field(pattern=TRAILER_KEY.pattern)
    value: str = Field(min_length=1, pattern=r"^[^\r\n]+$")

    @model_validator(mode="after")
    def reject_reserved_keys(self) -> Self:
        """保留由脚本生成或单独渲染的 trailer key。"""

        if self.key.lower() in {"assisted-by", "breaking-change"}:
            raise ValueError(f"reserved trailer key: {self.key}")
        return self


class CommitSpec(StrictModel):
    """结构化提交描述。"""

    subject: str = Field(pattern=CONVENTIONAL_SUBJECT.pattern)
    body: str | None = Field(default=None, min_length=1)
    breaking_change: BreakingChange | None = None
    trailers: list[Trailer] = Field(default_factory=list)
    paths: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def reject_escaped_newlines(cls, value: Any) -> Any:
        """在解析字段前拒绝字面量转义换行。"""

        reject_literal_newlines(value)
        return value

    @model_validator(mode="after")
    def validate_breaking_pair(self) -> Self:
        """要求 breaking 标题和详情成对出现。"""

        subject_is_breaking = BREAKING_SUBJECT.fullmatch(self.subject) is not None
        if subject_is_breaking != (self.breaking_change is not None):
            raise ValueError(
                "breaking subject and breaking_change must be provided together"
            )
        return self

    @model_validator(mode="after")
    def validate_paths(self) -> Self:
        """限制 paths 为不重复的仓库相对路径。"""

        if len(self.paths) != len(set(self.paths)):
            raise ValueError("paths must not contain duplicates")
        for raw_path in self.paths:
            path = Path(raw_path)
            if not raw_path.strip() or path.is_absolute() or ".." in path.parts:
                raise ValueError(f"path must be repository-relative: {raw_path!r}")
        return self


class ThreadReadThread(BaseModel):
    """只解析 thread/read 返回的 rollout 路径。"""

    path: str | None = None


class ThreadReadResponse(BaseModel):
    """只解析 thread/read 中提交所需的 thread 字段。"""

    thread: ThreadReadThread


def load_spec(text: str) -> CommitSpec:
    """从 YAML 文本解析并校验提交描述。"""

    payload = yaml.safe_load(text)
    if not isinstance(payload, dict):
        raise CommitError("YAML root must be a mapping")
    return CommitSpec.model_validate(payload)


def normalize_footer_text(value: str) -> str:
    """把 breaking 详情压缩为 footer 可用的单行文本。"""

    return " ".join(value.split())


def render_message(spec: CommitSpec, assisted_by: str | None) -> str:
    """将结构化描述渲染为带真实换行的提交信息。"""

    blocks = [spec.subject]
    if spec.body is not None:
        blocks.append(spec.body.rstrip("\n"))

    if spec.breaking_change is not None:
        impact = normalize_footer_text(spec.breaking_change.impact)
        migration = normalize_footer_text(spec.breaking_change.migration)
        blocks.append(f"BREAKING CHANGE: 影响范围：{impact} 迁移方式：{migration}")

    trailers = [f"{item.key}: {item.value}" for item in spec.trailers]
    if assisted_by is not None:
        trailers.append(f"Assisted-by: {assisted_by}")
    if trailers:
        blocks.append("\n".join(trailers))
    return "\n\n".join(blocks) + "\n"


def require_thread_id() -> str:
    """读取自动探测模型所需的 Codex thread ID。"""

    thread_id = os.environ.get("CODEX_THREAD_ID", "").strip()
    if not thread_id:
        raise CommitError(
            "missing CODEX_THREAD_ID; use --model MODEL or --skip-assisted-by"
        )
    return thread_id


def resolve_codex_bin() -> str:
    """定位宿主机 Codex 可执行文件。"""

    explicit = os.environ.get("CODEX_BIN", "").strip()
    if explicit:
        return explicit
    resolved = shutil.which("codex")
    if resolved:
        return resolved
    raise CommitError(
        "host Codex binary not found; set CODEX_BIN, use --model MODEL, "
        "or use --skip-assisted-by"
    )


def read_latest_model_name(rollout_path: Path) -> str:
    """从 rollout 中读取最后一条完整 turn_context 的模型名。"""

    model_name = ""
    try:
        with rollout_path.open(encoding="utf-8") as rollout:
            for line_number, line in enumerate(rollout, start=1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    if not line.endswith("\n"):
                        break
                    raise CommitError(
                        f"invalid rollout JSON at line {line_number}: {rollout_path}"
                    ) from exc
                if item.get("type") != "turn_context":
                    continue
                payload = item.get("payload")
                if not isinstance(payload, dict):
                    continue
                candidate = payload.get("model")
                if isinstance(candidate, str) and candidate.strip():
                    model_name = candidate.strip()
    except OSError as exc:
        raise CommitError(
            f"failed to read Codex rollout {rollout_path}: {exc}"
        ) from exc

    if not model_name:
        raise CommitError(f"failed to resolve model from rollout: {rollout_path}")
    return model_name


def resolve_model_name() -> str:
    """通过只读 Codex thread 信息解析当前模型名。"""

    thread_id = require_thread_id()
    config = CodexConfig(
        codex_bin=resolve_codex_bin(),
        client_name="codex-repository-workflow",
        client_title="Codex Repository Workflow",
        experimental_api=False,
    )
    try:
        with CodexClient(config) as client:
            client.initialize()
            response = client.request(
                "thread/read",
                {"threadId": thread_id, "includeTurns": False},
                response_model=ThreadReadResponse,
            )
    except CodexError as exc:
        raise CommitError(f"failed to resolve model via Codex SDK: {exc}") from exc
    except OSError as exc:
        raise CommitError(f"failed to start Codex SDK app-server: {exc}") from exc

    rollout_path = str(response.thread.path or "").strip()
    if not rollout_path:
        raise CommitError(f"thread {thread_id} does not have a rollout path")
    return read_latest_model_name(Path(rollout_path))


def assisted_by_value(model: str | None, skip: bool) -> str | None:
    """根据 CLI 参数返回 Assisted-by 值。"""

    if model is not None and skip:
        raise CommitError("--model and --skip-assisted-by are mutually exclusive")
    if skip:
        return None
    model_name = model.strip() if model is not None else resolve_model_name()
    if not model_name:
        raise CommitError("--model must not be empty")
    return f"{AGENT_NAME}:{model_name}"


def run_git(repo: Path, arguments: list[str], *, input_text: str | None = None) -> str:
    """在目标仓库执行 Git 并返回标准输出。"""

    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=repo,
            input=input_text,
            text=True,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise CommitError(
            f"git {' '.join(arguments)} failed: {detail.strip()}"
        ) from exc
    return result.stdout


def validate_rendered_message(message: str, assisted_by: str | None) -> None:
    """按是否启用 Assisted-by 选择验证强度。"""

    if assisted_by is not None:
        validate_message(message, assisted_by)
        return
    validate_message(message, None)


def list_untracked_paths(repo: Path, paths: list[str]) -> list[str]:
    """返回 paths 范围内尚未进入 index 的文件。"""

    output = run_git(
        repo,
        ["ls-files", "--others", "--exclude-standard", "-z", "--", *paths],
    )
    return [path for path in output.split("\0") if path]


def create_commit(
    repo: Path, spec: CommitSpec, message: str, assisted_by: str | None
) -> str:
    """使用临时 message file 创建并复核 commit。"""

    validate_rendered_message(message, assisted_by)
    run_git(repo, ["rev-parse", "--show-toplevel"])

    untracked_paths = list_untracked_paths(repo, spec.paths) if spec.paths else []
    if untracked_paths:
        run_git(repo, ["add", "--intent-to-add", "--", *untracked_paths])

    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", suffix=".txt"
    ) as message_file:
        message_file.write(message)
        message_file.flush()
        arguments = ["commit"]
        if spec.paths:
            arguments.append("--only")
        arguments.extend(["-F", message_file.name])
        if spec.paths:
            arguments.extend(["--", *spec.paths])
        try:
            run_git(repo, arguments)
        except CommitError:
            if untracked_paths:
                run_git(
                    repo,
                    ["update-index", "--force-remove", "--", *untracked_paths],
                )
            raise

    committed_message = run_git(repo, ["show", "-s", "--format=%B", "HEAD"])
    validate_rendered_message(committed_message, assisted_by)
    return run_git(repo, ["rev-parse", "HEAD"]).strip()


@app.command()
def main(
    spec_file: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, readable=True, resolve_path=True),
    ],
    repo: Annotated[
        Path,
        typer.Option("--repo", exists=True, file_okay=False, resolve_path=True),
    ] = Path("."),
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="只渲染和校验，不创建提交。")
    ] = False,
    json_output: Annotated[
        bool, typer.Option("--json", help="输出机器可读 JSON。")
    ] = False,
    model: Annotated[
        str | None,
        typer.Option("--model", help="显式指定 Codex 模型并跳过自动探测。"),
    ] = None,
    skip_assisted_by: Annotated[
        bool,
        typer.Option(
            "--skip-assisted-by",
            help="跳过模型探测且不添加 Assisted-by trailer。",
        ),
    ] = False,
) -> None:
    """从 SPEC_FILE 创建一个结构化 Git commit。"""

    try:
        spec = load_spec(spec_file.read_text(encoding="utf-8"))
        assisted_by = assisted_by_value(model, skip_assisted_by)
        message = render_message(spec, assisted_by)
        validate_rendered_message(message, assisted_by)
        commit_sha = None
        if not dry_run:
            commit_sha = create_commit(repo, spec, message, assisted_by)
    except (
        OSError,
        yaml.YAMLError,
        ValidationError,
        CommitError,
    ) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if json_output:
        typer.echo(
            json.dumps(
                {"commit": commit_sha, "message": message},
                ensure_ascii=False,
            )
        )
    else:
        typer.echo(message, nl=False)
        if commit_sha is not None:
            typer.echo(f"Created commit {commit_sha}", err=True)


if __name__ == "__main__":
    app()
