#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "google-api-python-client>=2.199.0",
#     "google-auth-httplib2>=0.4.1",
#     "google-auth-oauthlib>=1.4.0",
#     "httpx2>=2.12.0",
#     "httpxyz>=0.31.2",
#     "markdown-it-py>=4.2.0",
#     "openai-codex>=0.147.0",
#     "pydantic>=2.13.4",
#     "pytest>=9.1.1",
#     "pyyaml>=6.0.3",
#     "rich>=15.0.0",
#     "tomli-w>=1.2.0",
#     "typer>=0.27.1",
# ]
# ///

"""自动发现并运行仓库内全部 Python 测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TEST_ROOTS = (REPOSITORY_ROOT / "scripts", REPOSITORY_ROOT / "skills")


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
