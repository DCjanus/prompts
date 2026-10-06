#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""创建 PR，默认欢迎维护者修改并核验实际权限。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

NOTICE = "Maintainer edits are welcome—feel free to adjust the implementation to fit the project."


def gh(*args: str, payload: dict | None = None) -> str:
    """执行 gh；请求正文通过 stdin 传递。"""
    command = ["gh", *args]
    if payload is not None:
        command.extend(["--input", "-"])
    result = subprocess.run(
        command,
        input=json.dumps(payload) if payload is not None else None,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def read_pr(url: str) -> dict:
    """从创建结果定位 PR，兼容 GitHub Enterprise。"""
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")
    if len(parts) != 4 or parts[2] != "pull" or not parts[3].isdigit():
        raise ValueError(f"无法识别 PR URL：{url}")
    return json.loads(
        gh(
            "api",
            "--hostname",
            parsed.netloc,
            f"repos/{parts[0]}/{parts[1]}/pulls/{parts[3]}",
        )
    )


def verify_permission(url: str, expected: bool) -> dict:
    """个人 fork 的权限不符合要求时修正并回读，保留已创建 URL。"""
    pr = read_pr(url)
    head = pr["head"]["repo"]
    base = pr["base"]["repo"]
    applicable = (
        head is not None
        and head["id"] != base["id"]
        and head["owner"]["type"] == "User"
    )
    if applicable and pr.get("maintainer_can_modify") is not expected:
        parsed = urlparse(url)
        gh(
            "api",
            "--hostname",
            parsed.netloc,
            f"repos/{base['full_name']}/pulls/{pr['number']}",
            "--method",
            "PATCH",
            payload={"maintainer_can_modify": expected},
        )
        pr = read_pr(url)
        if pr.get("maintainer_can_modify") is not expected:
            raise ValueError(f"PR 已创建，但维护者修改权限核验失败：{url}")
    return pr


def create(args: argparse.Namespace) -> str:
    """正文使用临时副本；不修改或删除调用方文件。"""
    body = args.body_file.read_text(encoding="utf-8")
    if not body.strip():
        raise ValueError("PR 正文不能为空")
    target = json.loads(gh("repo", "view", args.repo, "--json", "nameWithOwner,url"))
    viewer = gh(
        "api", "--hostname", urlparse(target["url"]).netloc, "user", "--jq", ".login"
    )
    external = target["nameWithOwner"].split("/", 1)[0].casefold() != viewer.casefold()
    if external and not args.no_notice and args.notice not in body:
        body = f"{body.rstrip()}\n\n{args.notice}\n"
    with tempfile.TemporaryDirectory(prefix="github-pr-") as temporary:
        body_path = Path(temporary) / "body.md"
        body_path.write_text(body, encoding="utf-8")
        command = [
            "pr",
            "create",
            "--repo",
            args.repo,
            "--base",
            args.base,
            "--head",
            args.head,
            "--title",
            args.title,
            "--body-file",
            str(body_path),
        ]
        if args.draft:
            command.append("--draft")
        if args.no_maintainer_edit:
            command.append("--no-maintainer-edit")
        url = gh(*command)
    try:
        pr = verify_permission(url, not args.no_maintainer_edit)
        if (
            pr.get("title") != args.title
            or (pr.get("body") or "").strip() != body.strip()
        ):
            raise ValueError("标题或正文回读不一致")
    except (ValueError, KeyError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"PR 已创建，请勿重复创建；核验失败：{url}：{exc}") from exc
    return url


def main() -> int:
    """从资源与动作逐层发现参数。"""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("create", help="创建并核验 PR")
    for name in ("repo", "base", "head", "title"):
        command.add_argument(f"--{name}", required=True)
    command.add_argument("--body-file", type=Path, required=True)
    command.add_argument("--draft", action="store_true")
    command.add_argument(
        "--no-maintainer-edit", action="store_true", help="明确关闭修改权限"
    )
    command.add_argument(
        "--no-notice", action="store_true", help="已有等价声明或项目禁止附加声明时使用"
    )
    command.add_argument("--notice", default=NOTICE, help="按项目语言替换默认声明")
    args = parser.parse_args()
    try:
        print(create(args))
        return 0
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
