"""验证 PR 正文传递与修改权限的实际创建契约。"""

import argparse
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "github_pr.py"
spec = importlib.util.spec_from_file_location("github_pr", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class GitHubPrTest(unittest.TestCase):
    def test_create_preserves_body_and_source(self):
        original = "## What\n\nTechnical\n\n---\n\nUser-authored footer\n"
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "body.md"
            source.write_text(original)
            args = argparse.Namespace(
                repo="upstream/repo",
                base="main",
                head="DCjanus:fix",
                title="Fix",
                body_file=source,
                draft=False,
                no_maintainer_edit=False,
                assignee=["owner"],
            )

            def gh(*command, **kwargs):
                self.assertEqual(command[:2], ("pr", "create"))
                body = Path(command[command.index("--body-file") + 1]).read_text()
                self.assertEqual(body, original)
                self.assertNotIn("--no-maintainer-edit", command)
                self.assertIn("--assignee", command)
                return "https://github.com/upstream/repo/pull/1"

            with (
                patch.object(module, "gh", side_effect=gh),
                patch.object(
                    module,
                    "verify_permission",
                    return_value={"title": "Fix", "body": original},
                ),
            ):
                module.create(args)
            self.assertEqual(source.read_text(), original)
            args.dry_run = True
            with patch.object(module, "gh") as gh_mock:
                self.assertEqual(json.loads(module.create(args)), {"body": original})
                gh_mock.assert_not_called()

    def test_update_preserves_body_and_sets_assignees(self):
        original = "Technical\n\n---\n\nUser-authored footer\n"
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "body.md"
            source.write_text(original)
            args = argparse.Namespace(
                repo="upstream/repo",
                pr="1",
                body_file=source,
                dry_run=True,
                title="Fix",
                assignee=["owner"],
            )
            actual = {
                "url": "https://github.com/upstream/repo/pull/1",
                "title": "Old",
                "body": "Old",
            }
            writes = []

            def gh(*command, **kwargs):
                if command[:2] == ("pr", "view"):
                    return json.dumps(actual)
                self.assertIn("repos/upstream/repo/issues/1", command)
                writes.append(kwargs["payload"])
                actual.update(kwargs["payload"])
                return "{}"

            with (
                patch.object(module, "gh", side_effect=gh),
                patch.object(module, "read_pr", return_value=actual),
            ):
                self.assertEqual(json.loads(module.update(args)), {"body": original})
                self.assertEqual(writes, [])
                args.dry_run = False
                module.update(args)
            self.assertEqual(
                writes, [{"body": original, "title": "Fix", "assignees": ["owner"]}]
            )
            self.assertEqual(source.read_text(), original)

    def test_permission_repair_and_non_applicable(self):
        for owner_type, same_repo, repair in (
            ("User", False, True),
            ("Organization", False, False),
            ("User", True, False),
        ):
            with self.subTest(owner_type=owner_type, same_repo=same_repo):
                pr = {
                    "number": 1,
                    "maintainer_can_modify": False,
                    "head": {
                        "repo": {
                            "id": 1 if same_repo else 2,
                            "owner": {"type": owner_type},
                        }
                    },
                    "base": {"repo": {"id": 1, "full_name": "upstream/repo"}},
                }
                fixed = dict(pr, maintainer_can_modify=True)
                with (
                    patch.object(module, "read_pr", side_effect=[pr, fixed]),
                    patch.object(module, "gh") as gh,
                ):
                    module.verify_permission(
                        "https://github.com/upstream/repo/pull/1", True
                    )
                    self.assertEqual(gh.call_count, int(repair))

    def test_failed_verification_preserves_url(self):
        pr = {
            "number": 1,
            "maintainer_can_modify": False,
            "head": {"repo": {"id": 2, "owner": {"type": "User"}}},
            "base": {"repo": {"id": 1, "full_name": "upstream/repo"}},
        }
        with (
            patch.object(module, "read_pr", return_value=pr),
            patch.object(module, "gh"),
            self.assertRaisesRegex(
                ValueError, "https://github.com/upstream/repo/pull/1"
            ),
        ):
            module.verify_permission("https://github.com/upstream/repo/pull/1", True)
