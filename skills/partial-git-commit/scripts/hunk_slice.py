#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "typer>=0.20.0",
#     "unidiff2>=0.7.8",
# ]
# ///
"""
分页预览 unified diff 的 hunk，并按 hunk ID 生成子集 patch。
设计给 token 受限的代理：默认只列部分 hunk 缩略信息，按需迭代获取/保留。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

import subprocess
import sys
import tempfile

import typer
from unidiff import PatchSet


def flatten_hunks(patch: PatchSet) -> List[Tuple[str, str, object]]:
    items: List[Tuple[str, str, object]] = []
    seen: Dict[Tuple[str, int], int] = {}
    for file_patch in patch:
        for hunk in file_patch:
            key = (file_patch.path, hunk.target_start)
            seen[key] = seen.get(key, 0) + 1
            suffix = f":{seen[key]}" if seen[key] > 1 else ""
            hid = f"{file_patch.path}:{hunk.target_start}{suffix}"
            items.append((hid, file_patch.path, hunk))
    return items


def render_thumb(hid: str, path: str, hunk, added_preview: int, removed_preview: int) -> str:
    # 按出现顺序最多显示 5 行 diff，超出用省略号；多行分行展示以便阅读
    lines = [f"[{hid}] {path}:{hunk.target_start} (+{hunk.added} -{hunk.removed})"]
    shown = 0
    for line in hunk:
        if shown >= 5:
            lines.append("  ...")
            break
        mark = "+" if line.is_added else "-" if line.is_removed else " "
        lines.append(f"  {mark}{line.value.rstrip()}")
        shown += 1
    return "\n".join(lines)


def list_hunks(
    patch: PatchSet,
    start: int,
    count: int,
) -> None:
    all_hunks = flatten_hunks(patch)
    total = len(all_hunks)
    if total == 0:
        typer.echo("无 hunk")
        return
    start_idx = max(0, start - 1)
    end_idx = min(total, start_idx + count)
    for hid, path, hunk in all_hunks[start_idx:end_idx]:
        typer.echo(render_thumb(hid, path, hunk, 0, 0))
    typer.echo(f"-- 显示 {start}-{end_idx} / 总计 {total} --")


def write_selected(patch: PatchSet, keep_ids: List[str], out_path: Path) -> None:
    keep = set(keep_ids)
    written = 0
    with out_path.open("w", encoding="utf-8") as fh:
        seen: Dict[Tuple[str, int], int] = {}
        for file_patch in patch:
            kept = []
            for hunk in file_patch:
                key = (file_patch.path, hunk.target_start)
                seen[key] = seen.get(key, 0) + 1
                suffix = f":{seen[key]}" if seen[key] > 1 else ""
                hid = f"{file_patch.path}:{hunk.target_start}{suffix}"
                if hid in keep:
                    kept.append(hunk)
            if not kept:
                continue
            # patch_info 为 PatchInfo 对象，需转成文本写入
            header = str(file_patch.patch_info)
            fh.write(header)
            if header and not header.endswith("\n"):
                fh.write("\n")
            for hunk in kept:
                text = str(hunk)
                fh.write(text)
                if not text.endswith("\n"):
                    fh.write("\n")
                written += 1
    typer.echo(f"已保留 {written} 个 hunk -> {out_path}")


def apply_to_index(patch_path: Path) -> None:
    try:
        subprocess.run(
            ["git", "apply", "--cached", str(patch_path)],
            check=True,
            text=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        typer.echo(f"git apply --cached 失败：{e.stderr or e.stdout}")
        raise typer.Exit(code=1)
    typer.echo("已将精简 patch 写入暂存区")


def show_cached_diff() -> None:
    try:
        result = subprocess.run(
            ["git", "diff", "--cached"],
            check=True,
            text=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        typer.echo(f"git diff --cached 失败：{e.stderr or e.stdout}")
        raise typer.Exit(code=1)
    if result.stdout.strip():
        typer.echo(result.stdout)
    else:
        typer.echo("暂存区为空")


def commit_cached(message: str) -> None:
    # 先确认暂存区非空
    quiet = subprocess.run(["git", "diff", "--cached", "--quiet"])
    if quiet.returncode == 0:
        typer.echo("暂存区为空，未提交；请先保留 hunk")
        raise typer.Exit(code=1)
    try:
        result = subprocess.run(
            ["git", "commit", "-m", message],
            check=True,
            text=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        typer.echo(f"git commit 失败：{e.stderr or e.stdout}")
        raise typer.Exit(code=1)
    typer.echo(result.stdout.strip() or "提交完成")


def load_patch_from_git(paths: List[Path] | None) -> PatchSet:
    # 包含已暂存与未暂存，统一对比 HEAD
    cmd = ["git", "diff", "--no-color", "--no-ext-diff", "HEAD"]
    if paths:
        cmd.append("--")
        cmd.extend(str(p) for p in paths)

    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        typer.echo(f"git diff 失败：{e}")
        raise typer.Exit(code=1)

    if not result.stdout.strip():
        typer.echo("diff 为空，未生成 hunk")
        raise typer.Exit(code=0)

    return PatchSet(result.stdout.splitlines(keepends=True))


app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="分页浏览 diff hunk，或按 hunk ID 生成子集 patch。",
)


@app.command("list", help="分页列出 hunk 缩略信息")
def cmd_list(
    paths: List[Path] = typer.Option(
        None,
        "--path",
        "-P",
        help="限定路径，多次传入；未提供则全仓库",
    ),
    start: int = typer.Option(1, "--start", "-s", min=1, help="起始 hunk 序号（1 基）"),
    count: int = typer.Option(5, "--count", "-c", min=1, help="展示 hunk 数量"),
) -> None:
    patch_set = load_patch_from_git(paths)
    list_hunks(patch_set, start, count)


@app.command("commit", help="按 hunk ID 直接提交（生成并应用精简 patch）")
def cmd_commit(
    paths: List[Path] = typer.Option(
        None,
        "--path",
        "-P",
        help="限定路径，多次传入；未提供则全仓库",
    ),
    keep: List[str] = typer.Option(
        ...,
        "--keep",
        "-k",
        help="保留的 hunk ID，可多次传入，如 --keep src/app.py:42",
    ),
    message: str = typer.Option(
        ...,
        "--message",
        "-m",
        help="提交说明，必填；脚本会应用精简 patch 并 git commit -m <message>",
    ),
    keep_temp: bool = typer.Option(
        False,
        "--keep-temp",
        help="提交后保留临时 patch 文件并输出路径；默认提交成功后删除",
    ),
) -> None:
    patch_set = load_patch_from_git(paths)
    if not keep:
        typer.echo("未提供任何 hunk ID")
        raise typer.Exit(code=1)

    with tempfile.NamedTemporaryFile(prefix="hunk_slice_", suffix=".patch", delete=False) as tf:
        temp_path = Path(tf.name)
    write_selected(patch_set, keep, temp_path)
    apply_to_index(temp_path)
    commit_cached(message)
    if keep_temp:
        typer.echo(f"保留临时 patch：{temp_path}")
    else:
        try:
            temp_path.unlink()
            typer.echo(f"已删除临时 patch: {temp_path}")
        except OSError:
            typer.echo(f"删除临时 patch 失败，手动清理：{temp_path}")


if __name__ == "__main__":
    app()
