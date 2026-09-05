"""验证初始化产物、覆盖保护和失败时的文件边界。"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import tomllib
from typer.testing import CliRunner

SCRIPT = Path(__file__).parents[1] / "init_cli.py"
SPEC = importlib.util.spec_from_file_location("uv_cli_initializer", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
initializer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(initializer)
runner = CliRunner()


@pytest.fixture(autouse=True)
def offline_uv(monkeypatch):
    """只使用测试进程已有解释器，不依赖网络。"""
    monkeypatch.setenv("UV_OFFLINE", "1")
    monkeypatch.setenv("UV_PYTHON_DOWNLOADS", "never")


def test_creates_executable_script_in_requested_directory(tmp_path, monkeypatch):
    """调用目录决定相对目标，产物可在任意目录独立执行。"""
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "skill with spaces" / "scripts" / "sample.py"
    result = runner.invoke(
        initializer.app,
        [str(target.relative_to(tmp_path)), "--python", sys.executable, "--json"],
    )
    assert result.exit_code == 0, result.output
    assert Path(json.loads(result.stdout)["path"]) == target
    content = target.read_text()
    metadata = content.split("# /// script\n", 1)[1].split("# ///", 1)[0]
    declaration = tomllib.loads("\n".join(line[2:] for line in metadata.splitlines()))
    assert declaration["dependencies"] == []
    assert "requires-python" in declaration
    assert list(target.parent.iterdir()) == [target]
    uv = shutil.which("uv")
    assert uv is not None
    commands = [[uv, "run", "--script", str(target)]]
    if os.name == "posix":
        assert os.access(target, os.X_OK)
        commands.append([str(target)])
    for command in commands:
        completed = subprocess.run(
            command, cwd=tmp_path, capture_output=True, text=True, check=False
        )
        assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("kind", ["file", "directory", "dangling-symlink"])
def test_does_not_overwrite_existing_paths(tmp_path, kind):
    """现有文件、目录及悬空软链接均保持原状。"""
    target = tmp_path / "existing.py"
    if kind == "file":
        target.write_bytes(b"user content\n")
    elif kind == "directory":
        target.mkdir()
    else:
        target.symlink_to(tmp_path / "missing.py")
    result = runner.invoke(initializer.app, [str(target), "--json"])
    assert result.exit_code == 1
    assert "error" in json.loads(result.stderr)
    if kind == "file":
        assert target.read_bytes() == b"user content\n"
    elif kind == "directory":
        assert target.is_dir()
    else:
        assert target.is_symlink()
        assert not target.exists()


def test_invalid_dependency_leaves_no_partial_script(tmp_path):
    """依赖声明失败时不留下看似可用的入口或临时文件。"""
    target = tmp_path / "invalid.py"
    result = runner.invoke(
        initializer.app,
        [str(target), "--python", sys.executable, "-d", "invalid=*", "--json"],
    )
    assert result.exit_code == 1
    assert "error" in json.loads(result.stderr)
    assert list(tmp_path.iterdir()) == []
