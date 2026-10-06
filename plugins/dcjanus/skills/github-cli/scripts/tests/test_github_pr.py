"""验证 PR 默认声明与修改权限的实际创建契约。"""

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
    def test_create_notice_and_preserve_source(self):
        for owner, no_notice, original, expected in (
            ("upstream", False, "Original", "Original\n\n" + module.NOTICE),
            ("DCjanus", False, "Original", "Original"),
            ("upstream", True, "Equivalent notice", "Equivalent notice"),
            ("upstream", False, module.NOTICE, module.NOTICE),
        ):
            with (
                self.subTest(owner=owner, original=original),
                tempfile.TemporaryDirectory() as directory,
            ):
                source = Path(directory) / "body.md"
                source.write_text(original)
                args = argparse.Namespace(
                    repo=f"{owner}/repo",
                    base="main",
                    head="DCjanus:fix",
                    title="Fix",
                    body_file=source,
                    draft=False,
                    no_notice=no_notice,
                    notice=module.NOTICE,
                    no_maintainer_edit=False,
                )

                def gh(*command, args=args, expected=expected, **kwargs):
                    if command[0] == "repo":
                        return json.dumps(
                            {
                                "nameWithOwner": args.repo,
                                "url": "https://github.com/" + args.repo,
                            }
                        )
                    if command[0] == "api":
                        return "DCjanus"
                    body = Path(command[command.index("--body-file") + 1]).read_text()
                    self.assertEqual(body.strip(), expected)
                    self.assertNotIn("--no-maintainer-edit", command)
                    return "https://github.com/upstream/repo/pull/1"

                with (
                    patch.object(module, "gh", side_effect=gh),
                    patch.object(
                        module,
                        "verify_permission",
                        return_value={"title": "Fix", "body": expected},
                    ),
                ):
                    module.create(args)
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
