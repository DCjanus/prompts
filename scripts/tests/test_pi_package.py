"""验证 Pi package 与 Codex plugin 复用同一套 skills。"""

from __future__ import annotations

import json
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_pi_package_reuses_codex_plugin_skills():
    package = json.loads((REPOSITORY_ROOT / "package.json").read_text())
    plugin = json.loads(
        (REPOSITORY_ROOT / "plugins/dcjanus/.codex-plugin/plugin.json").read_text()
    )
    codex_skills = (REPOSITORY_ROOT / "plugins/dcjanus" / plugin["skills"]).resolve()

    entries = package["pi"]["skills"]
    includes = [entry for entry in entries if not entry.startswith(("!", "+", "-"))]
    assert [(REPOSITORY_ROOT / entry).resolve() for entry in includes] == [codex_skills]

    excludes = [entry for entry in entries if entry.startswith("!")]
    assert excludes
    for pattern in excludes:
        name = pattern.removeprefix("!").removeprefix("**/")
        assert (codex_skills / name / "SKILL.md").is_file()
