#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///

"""验证 repository-workflow 创建的 Git commit message。"""

from __future__ import annotations

import argparse
import re
import subprocess

BREAKING_TITLE = re.compile(r"^[a-z][a-z0-9-]*(?:\([^\r\n)]+\))?!: .+")
BREAKING_PREFIX = "BREAKING CHANGE:"


class ValidationError(RuntimeError):
    """提交信息不符合 repository-workflow 约定。"""


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
        raise ValidationError(f"failed to parse Git trailers: {exc}") from exc
    return result.stdout.splitlines()


def validate_message(message: str, assisted_by: str | None) -> None:
    """验证 breaking 标记与预期的 Assisted-by trailer。"""

    lines = message.rstrip("\n").splitlines()
    if not lines:
        raise ValidationError("commit message is empty")

    title_is_breaking = BREAKING_TITLE.fullmatch(lines[0]) is not None
    breaking_footers = [line for line in lines[1:] if line.startswith(BREAKING_PREFIX)]
    if title_is_breaking and len(breaking_footers) != 1:
        raise ValidationError(
            "a breaking title must contain exactly one BREAKING CHANGE footer"
        )
    if not title_is_breaking and breaking_footers:
        raise ValidationError("a BREAKING CHANGE footer requires ! in the title")
    if breaking_footers:
        footer_value = breaking_footers[0].removeprefix(BREAKING_PREFIX).strip()
        if not footer_value or footer_value.endswith(":"):
            raise ValidationError("malformed BREAKING CHANGE footer")

    assisted_by_trailers = [
        trailer
        for trailer in parsed_trailers(message)
        if trailer.lower().startswith("assisted-by:")
    ]
    if assisted_by is None:
        if assisted_by_trailers:
            raise ValidationError("Assisted-by must be absent when validation skips it")
    else:
        expected = f"Assisted-by: {assisted_by}"
        occurrences = assisted_by_trailers.count(expected)
        if occurrences != 1 or len(assisted_by_trailers) != 1:
            raise ValidationError(
                f"expected exactly one parsed trailer {expected!r}, got {occurrences}"
            )


def read_commit_message(revision: str) -> str:
    """读取指定 revision 的完整提交信息。"""

    try:
        result = subprocess.run(
            ["git", "show", "-s", "--format=%B", revision],
            text=True,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValidationError(f"failed to read commit {revision!r}: {exc}") from exc
    return result.stdout


def main() -> None:
    """解析参数并验证一个 Git commit。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assisted-by", required=True, metavar="AGENT:MODEL")
    parser.add_argument("--revision", default="HEAD")
    arguments = parser.parse_args()

    try:
        validate_message(
            read_commit_message(arguments.revision),
            arguments.assisted_by,
        )
    except ValidationError as exc:
        parser.exit(1, f"error: {exc}\n")
    print(f"Validated commit message for {arguments.revision}.")


if __name__ == "__main__":
    main()
