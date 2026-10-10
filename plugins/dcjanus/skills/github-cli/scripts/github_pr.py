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

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "repository-workflow/scripts")
)
from collaboration_notice import CHINESE, ENGLISH, decide, render

NOTICE = ENGLISH


def notice_body(args, body: str, pr: dict | None = None) -> tuple[str, str]:
    """按目标仓库角色和负责人统一处理声明。"""
    target = json.loads(gh("repo", "view", args.repo, "--json", "nameWithOwner,url"))
    host = urlparse(target["url"]).netloc
    actor = getattr(args, "actor", None)
    if actor is None:
        try:
            actor = gh("api", "--hostname", host, "user", "--jq", ".login")
        except subprocess.CalledProcessError:
            actor = ""
    assignees = getattr(args, "assignee", None)
    if assignees is None:
        assignees = [user["login"] for user in (pr or {}).get("assignees", [])]
    assigned = actor.casefold() in {name.casefold() for name in assignees}
    owner = target["nameWithOwner"].split("/", 1)[0]
    maintainer = True if owner.casefold() == actor.casefold() else None
    if maintainer is None and actor:
        try:
            permission = json.loads(
                gh(
                    "api",
                    "--hostname",
                    host,
                    f"repos/{target['nameWithOwner']}/collaborators/{actor}/permission",
                )
            )
            if permission.get("role_name") or permission.get("permission"):
                maintainer = (
                    permission.get("role_name") in {"maintain", "admin"}
                    or permission.get("permission") == "admin"
                )
        except (subprocess.CalledProcessError, ValueError):
            maintainer = None
    mode = (
        "never"
        if getattr(args, "no_notice", False)
        else getattr(args, "notice_mode", "auto")
    )
    include, reason = decide(mode, maintainer, assigned)
    notice = getattr(args, "notice", None) or (
        CHINESE if getattr(args, "notice_language", "en") == "zh" else ENGLISH
    )
    print(
        f"notice: {'include' if include else 'omit'} ({reason}); actor={actor}",
        file=sys.stderr,
    )
    return render(body, include, notice), reason


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
    body, reason = notice_body(args, body)
    if getattr(args, "dry_run", False):
        return json.dumps({"body": body, "notice_reason": reason}, ensure_ascii=False)
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
        for assignee in getattr(args, "assignee", None) or []:
            command.extend(["--assignee", assignee])
        url = gh(*command)
    try:
        pr = verify_permission(url, not args.no_maintainer_edit)
        actual_args = argparse.Namespace(**vars(args))
        actual_args.assignee = None
        final_body, _ = notice_body(actual_args, body, pr)
        if final_body != body:
            parsed = urlparse(url)
            gh(
                "api",
                "--hostname",
                parsed.netloc,
                f"repos/{target_repo(url)}/pulls/{pr['number']}",
                "--method",
                "PATCH",
                payload={"body": final_body},
            )
            body = final_body
            pr = read_pr(url)
        if (
            pr.get("title") != args.title
            or (pr.get("body") or "").strip() != body.strip()
        ):
            raise ValueError("标题或正文回读不一致")
    except (ValueError, KeyError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"PR 已创建，请勿重复创建；核验失败：{url}：{exc}") from exc
    return url


def target_repo(url: str) -> str:
    """从 PR URL 读取目标仓库。"""
    return "/".join(urlparse(url).path.strip("/").split("/")[:2])


def update(args) -> str:
    """更新正文，读取实际负责人并回读核验。"""
    pr = json.loads(
        gh(
            "pr",
            "view",
            args.pr,
            "--repo",
            args.repo,
            "--json",
            "url,title,body,assignees",
        )
    )
    body, reason = notice_body(args, args.body_file.read_text(encoding="utf-8"), pr)
    if args.dry_run:
        return json.dumps({"body": body, "notice_reason": reason}, ensure_ascii=False)
    payload = {"body": body}
    if args.title:
        payload["title"] = args.title
    if args.assignee is not None:
        payload["assignees"] = args.assignee
    url = pr["url"]
    parsed = urlparse(url)
    gh(
        "api",
        "--hostname",
        parsed.netloc,
        f"repos/{target_repo(url)}/issues/{parsed.path.split('/')[-1]}",
        "--method",
        "PATCH",
        payload=payload,
    )
    actual = read_pr(url)
    actual_args = argparse.Namespace(**vars(args))
    actual_args.assignee = None
    final_body, _ = notice_body(actual_args, body, actual)
    if final_body != body:
        gh(
            "api",
            "--hostname",
            parsed.netloc,
            f"repos/{target_repo(url)}/pulls/{parsed.path.split('/')[-1]}",
            "--method",
            "PATCH",
            payload={"body": final_body},
        )
        actual = read_pr(url)
        body = final_body
    if (actual.get("body") or "").strip() != body.strip() or (
        args.title and actual.get("title") != args.title
    ):
        raise ValueError(f"正文回读不一致：{url}")
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
    edit = commands.add_parser("update", help="更新正文并自动判断声明")
    edit.add_argument("pr", help="PR 编号或 URL")
    edit.add_argument("--repo", required=True)
    edit.add_argument("--body-file", type=Path, required=True)
    edit.add_argument("--title")
    for entry in (command, edit):
        entry.add_argument(
            "--actor", help="实际贡献者登录名；bot 操作时显式指定，默认当前登录账号"
        )
        entry.add_argument(
            "--assignee",
            action="append",
            help="负责人登录名；可重复，update 时替换负责人列表",
        )
        entry.add_argument(
            "--notice-mode", choices=["auto", "always", "never"], default="auto"
        )
        entry.add_argument("--notice-language", choices=["en", "zh"], default="en")
        entry.add_argument("--notice", help="替换分隔线及完整声明")
        entry.add_argument(
            "--dry-run",
            action="store_true",
            help="只查询，输出最终正文和判断理由，不写入平台",
        )
    args = parser.parse_args()
    try:
        print(create(args) if args.command == "create" else update(args))
        return 0
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
