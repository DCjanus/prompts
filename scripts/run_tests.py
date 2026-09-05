#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "duckdb>=1.5.5",
#     "google-api-python-client>=2.200.0",
#     "google-auth-httplib2>=0.4.2",
#     "google-auth-oauthlib>=1.4.1",
#     "httpx2>=2.12.0",
#     "httpxyz>=0.42.1",
#     "kittytgp>=0.0.2",
#     "markdown-it-py>=4.2.0",
#     "openai-codex>=0.147.0",
#     "pydantic>=2.13.5",
#     "pytest>=9.1.1",
#     "pyyaml>=6.0.3",
#     "resvg-py>=0.5.0",
#     "rich>=15.0.0",
#     "tomli-w>=1.2.0",
#     "typer>=0.27.2",
# ]
# ///

"""自动发现并运行仓库内全部 Python 测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TEST_ROOTS = (REPOSITORY_ROOT / "scripts", REPOSITORY_ROOT / "plugins")


def main() -> int:
    """使用隔离导入模式运行全部脚本与 skill 测试。"""
    return pytest.main(
        [
            "--import-mode=importlib",
            *(str(path) for path in TEST_ROOTS),
            *sys.argv[1:],
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
