from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts import upstream_skills


class UpstreamSkillsTest(unittest.TestCase):
    def test_load_manifest_and_detect_changed_skill(self) -> None:
        manifest_text = """
[[skills]]
name = "grilling"
repository = "mattpocock/skills"
path = "skills/productivity/grilling"
commit = "1111111111111111111111111111111111111111"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Path(tmpdir) / "upstream-skills.toml"
            manifest.write_text(manifest_text, encoding="utf-8")

            skills = upstream_skills.load_manifest(manifest)
            reports = upstream_skills.check_skills(
                skills,
                lambda _: "2222222222222222222222222222222222222222",
            )

        self.assertEqual(skills[0].name, "grilling")
        self.assertEqual(reports[0].status, "changed")
        self.assertTrue(reports[0].needs_attention)

    def test_matching_commit_is_current(self) -> None:
        skill = upstream_skills.TrackedSkill(
            name="domain-modeling",
            repository="mattpocock/skills",
            path="skills/engineering/domain-modeling",
            commit="a" * 40,
        )

        reports = upstream_skills.check_skills([skill], lambda _: "a" * 40)

        self.assertEqual(reports[0].status, "current")
        self.assertFalse(reports[0].needs_attention)

    def test_lookup_failure_needs_attention(self) -> None:
        skill = upstream_skills.TrackedSkill(
            name="grilling",
            repository="mattpocock/skills",
            path="skills/productivity/grilling",
            commit="a" * 40,
        )

        def fail(_: upstream_skills.TrackedSkill) -> str:
            raise upstream_skills.UpstreamLookupError("rate limited")

        reports = upstream_skills.check_skills([skill], fail)

        self.assertEqual(reports[0].status, "lookup failed")
        self.assertTrue(reports[0].needs_attention)
        self.assertEqual(reports[0].error, "rate limited")


if __name__ == "__main__":
    unittest.main()
