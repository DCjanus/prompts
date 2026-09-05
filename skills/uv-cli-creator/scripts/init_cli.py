#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "typer>=0.27.2",
# ]
# ///

"""初始化带 PEP 723 依赖和可执行入口的单文件 Python CLI。"""

from __future__ import annotations

import json
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(add_completion=False, pretty_exceptions_enable=False)
SHEBANG = "#!/usr/bin/env -S uv run --script\n#\n"


def initialize_cli(target: Path, dependencies: list[str], python: str | None) -> Path:
    """通过 uv 创建脚本，成功后写入目标路径且不覆盖已有文件。"""
    target = target.expanduser().absolute()
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"目标已存在：{target}")
    uv = shutil.which("uv")
    if uv is None:
        raise FileNotFoundError("未找到 uv，请先安装 uv 并加入 PATH")

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".uv-cli-", dir=target.parent) as folder:
        staged = Path(folder) / target.name
        command = [uv, "init", "--script", str(staged)]
        if python is not None:
            command.extend(["--python", python])
        subprocess.run(
            command, cwd=target.parent, check=True, capture_output=True, text=True
        )
        if dependencies:
            subprocess.run(
                [uv, "add", "--script", str(staged), "--", *dependencies],
                cwd=target.parent,
                check=True,
                capture_output=True,
                text=True,
            )
        content = SHEBANG + staged.read_text(encoding="utf-8")
        with target.open("x", encoding="utf-8", newline="\n") as output:
            output.write(content)
        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return target


@app.command()
def main(
    path: Annotated[Path, typer.Argument(help="新脚本路径；相对路径基于调用目录")],
    dependency: Annotated[
        list[str] | None,
        typer.Option("--dependency", "-d", help="交给 uv 添加的依赖，可重复指定"),
    ] = None,
    python: Annotated[
        str | None,
        typer.Option("--python", help="交给 uv 选择的 Python 版本或解释器路径"),
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="以 JSON 输出创建结果")
    ] = False,
) -> None:
    """初始化新脚本，自动添加依赖、shebang 和执行权限。"""
    try:
        target = initialize_cli(path, dependency or [], python)
    except (OSError, subprocess.CalledProcessError) as exc:
        message = (
            exc.stderr.strip()
            if isinstance(exc, subprocess.CalledProcessError) and exc.stderr
            else str(exc)
        )
        if json_output:
            typer.echo(json.dumps({"error": message}, ensure_ascii=False), err=True)
        else:
            typer.echo(f"初始化失败：{message}", err=True)
        raise typer.Exit(1) from exc
    if json_output:
        typer.echo(json.dumps({"path": str(target)}, ensure_ascii=False))
    else:
        typer.echo(f"已创建：{target}")


if __name__ == "__main__":
    app()
