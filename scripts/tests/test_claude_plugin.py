"""验证 Claude Code plugin 与 Codex plugin 复用同一套 skills 及调用策略。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPOSITORY_ROOT / "plugins/dcjanus"
SKILLS_ROOT = PLUGIN_ROOT / "skills"


def read_frontmatter(path: Path) -> dict:
    """读取 SKILL.md 开头的 YAML frontmatter。"""
    _, frontmatter, _ = path.read_text().split("---\n", 2)
    return yaml.safe_load(frontmatter)


def test_claude_marketplace_shares_codex_plugin():
    claude = json.loads(
        (REPOSITORY_ROOT / ".claude-plugin/marketplace.json").read_text()
    )
    codex = json.loads(
        (REPOSITORY_ROOT / ".agents/plugins/marketplace.json").read_text()
    )
    assert claude["name"] == codex["name"]

    [claude_entry] = claude["plugins"]
    [codex_entry] = codex["plugins"]
    assert claude_entry["name"] == codex_entry["name"]
    assert (REPOSITORY_ROOT / claude_entry["source"]).resolve() == (
        REPOSITORY_ROOT / codex_entry["source"]["path"]
    ).resolve()

    claude_plugin = json.loads((PLUGIN_ROOT / ".claude-plugin/plugin.json").read_text())
    codex_plugin = json.loads((PLUGIN_ROOT / ".codex-plugin/plugin.json").read_text())
    assert claude_plugin["name"] == codex_plugin["name"]
    # Claude Code 默认发现 skills/ 目录，需与 Codex 声明的目录一致。
    assert (PLUGIN_ROOT / codex_plugin["skills"]).resolve() == SKILLS_ROOT


def test_explicit_only_skills_match_between_codex_and_claude():
    for skill_md in sorted(SKILLS_ROOT.glob("*/SKILL.md")):
        metadata_path = skill_md.parent / "agents/openai.yaml"
        metadata = (
            yaml.safe_load(metadata_path.read_text()) if metadata_path.is_file() else {}
        )
        codex_implicit = (metadata.get("policy") or {}).get(
            "allow_implicit_invocation", True
        )
        claude_disabled = read_frontmatter(skill_md).get(
            "disable-model-invocation", False
        )
        assert claude_disabled is (not codex_implicit), skill_md.parent.name


@pytest.mark.skipif(shutil.which("claude") is None, reason="需要 Claude Code CLI")
def test_claude_marketplace_installs_all_skills(tmp_path):
    environment = {**os.environ, "CLAUDE_CONFIG_DIR": str(tmp_path)}

    def run(*arguments):
        return subprocess.run(
            ["claude", "plugin", *arguments],
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        ).stdout

    run("validate", "--strict", str(REPOSITORY_ROOT))
    run("validate", "--strict", str(PLUGIN_ROOT))
    run("marketplace", "add", str(REPOSITORY_ROOT))
    run("install", "dcjanus@dcjanus-plugins")
    details = run("details", "dcjanus@dcjanus-plugins")

    expected = sorted(path.parent.name for path in SKILLS_ROOT.glob("*/SKILL.md"))
    assert f"Skills ({len(expected)})" in details
    for name in expected:
        assert name in details
