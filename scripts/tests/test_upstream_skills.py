from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from scripts import upstream_skills


class UpstreamSkillsTest(unittest.TestCase):
    def test_github_token_takes_priority_without_calling_gh(self) -> None:
        with (
            mock.patch.dict(
                upstream_skills.os.environ,
                {"GITHUB_TOKEN": " github-token ", "GH_TOKEN": "gh-token"},
                clear=True,
            ),
            mock.patch.object(upstream_skills.shutil, "which") as which,
        ):
            auth = upstream_skills.resolve_github_auth()

        self.assertEqual(
            auth,
            upstream_skills.GitHubAuth(
                token="github-token",
                source="GITHUB_TOKEN",
            ),
        )
        which.assert_not_called()

    def test_uses_anonymous_access_when_gh_is_not_installed(self) -> None:
        with (
            mock.patch.dict(upstream_skills.os.environ, {}, clear=True),
            mock.patch.object(upstream_skills.shutil, "which", return_value=None),
        ):
            auth = upstream_skills.resolve_github_auth()

        self.assertEqual(
            auth,
            upstream_skills.GitHubAuth(token=None, source="anonymous"),
        )

    def test_returns_none_when_gh_is_not_logged_in(self) -> None:
        status = mock.Mock(returncode=1, stdout="", stderr="not logged in")
        with (
            mock.patch.dict(upstream_skills.os.environ, {}, clear=True),
            mock.patch.object(
                upstream_skills.shutil, "which", return_value="/usr/bin/gh"
            ),
            mock.patch.object(
                upstream_skills.subprocess,
                "run",
                return_value=status,
            ) as run,
        ):
            auth = upstream_skills.resolve_github_auth()

        self.assertEqual(
            auth,
            upstream_skills.GitHubAuth(token=None, source="anonymous"),
        )
        run.assert_called_once_with(
            ["/usr/bin/gh", "auth", "status", "--hostname", "github.com"],
            text=True,
            capture_output=True,
            check=False,
            env={},
        )

    def test_uses_token_from_logged_in_gh(self) -> None:
        status = mock.Mock(returncode=0, stdout="", stderr="")
        token_result = mock.Mock(returncode=0, stdout=" gh-auth-token\n", stderr="")
        with (
            mock.patch.dict(upstream_skills.os.environ, {}, clear=True),
            mock.patch.object(
                upstream_skills.shutil, "which", return_value="/usr/bin/gh"
            ),
            mock.patch.object(
                upstream_skills.subprocess,
                "run",
                side_effect=[status, token_result],
            ) as run,
        ):
            auth = upstream_skills.resolve_github_auth()

        self.assertEqual(
            auth,
            upstream_skills.GitHubAuth(
                token="gh-auth-token",
                source="gh auth token",
            ),
        )
        self.assertEqual(
            run.call_args_list[1],
            mock.call(
                ["/usr/bin/gh", "auth", "token", "--hostname", "github.com"],
                text=True,
                capture_output=True,
                check=False,
                env={},
            ),
        )

    def test_ignores_gh_token_when_resolving_stored_gh_login(self) -> None:
        status = mock.Mock(returncode=1, stdout="", stderr="not logged in")
        with (
            mock.patch.dict(
                upstream_skills.os.environ,
                {"GH_TOKEN": "ignored-token", "PATH": "/usr/bin"},
                clear=True,
            ),
            mock.patch.object(
                upstream_skills.shutil, "which", return_value="/usr/bin/gh"
            ),
            mock.patch.object(
                upstream_skills.subprocess,
                "run",
                return_value=status,
            ) as run,
        ):
            auth = upstream_skills.resolve_github_auth()

        self.assertEqual(
            auth,
            upstream_skills.GitHubAuth(token=None, source="anonymous"),
        )
        self.assertEqual(run.call_args.kwargs["env"], {"PATH": "/usr/bin"})

    def test_fetch_sends_resolved_token_in_authorization_header(self) -> None:
        skill = upstream_skills.TrackedSkill(
            name="domain-modeling",
            repository="mattpocock/skills",
            path="skills/engineering/domain-modeling",
            commit="a" * 40,
        )
        response = mock.MagicMock()
        response.__enter__.return_value = io.BytesIO(
            ('[{"sha":"' + "b" * 40 + '"}]').encode()
        )
        with mock.patch.object(
            upstream_skills,
            "urlopen",
            return_value=response,
        ) as urlopen:
            latest = upstream_skills.fetch_latest_commit(
                skill,
                timeout=1,
                token="resolved-token",
            )

        self.assertEqual(latest, "b" * 40)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer resolved-token")

    def test_main_reports_token_source_to_stderr_without_polluting_json(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.object(upstream_skills, "load_manifest", return_value=[]),
            mock.patch.object(
                upstream_skills,
                "resolve_github_auth",
                return_value=upstream_skills.GitHubAuth(
                    token="secret-token",
                    source="GITHUB_TOKEN",
                ),
            ),
            mock.patch.object(upstream_skills, "check_skills", return_value=[]),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            exit_code = upstream_skills.main(["--json"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            upstream_skills.json.loads(stdout.getvalue()),
            {"skill_count": 0, "attention_count": 0, "skills": []},
        )
        self.assertEqual(stderr.getvalue(), "GitHub API token source: GITHUB_TOKEN\n")
        self.assertNotIn("secret-token", stderr.getvalue())

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
