import hashlib
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest


def load_install_module():
    module_path = Path(__file__).resolve().parents[1] / "install_codex_cli.py"
    spec = importlib.util.spec_from_file_location("install_codex_cli", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load install_codex_cli module.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class InstallCodexCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_install_module()

    def test_installed_version_requires_exact_semver_match(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target_path = Path(temp_dir) / "codex"
            target_path.write_text("#!/bin/sh\n", encoding="utf-8")
            release = self.mod.Release(tag_name="rust-v0.136.0", assets=[])

            def fake_run(*args, **kwargs):
                return subprocess.CompletedProcess(
                    args=args[0],
                    returncode=0,
                    stdout="codex-cli 0.136.0-alpha.1\n",
                    stderr="",
                )

            original_run = self.mod.subprocess.run
            self.mod.subprocess.run = fake_run
            try:
                self.assertFalse(
                    self.mod.installed_version_matches(target_path, release)
                )
            finally:
                self.mod.subprocess.run = original_run

    def test_installed_version_accepts_exact_semver_match(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target_path = Path(temp_dir) / "codex"
            target_path.write_text("#!/bin/sh\n", encoding="utf-8")
            release = self.mod.Release(tag_name="rust-v0.136.0", assets=[])

            def fake_run(*args, **kwargs):
                return subprocess.CompletedProcess(
                    args=args[0],
                    returncode=0,
                    stdout="codex-cli 0.136.0\n",
                    stderr="",
                )

            original_run = self.mod.subprocess.run
            self.mod.subprocess.run = fake_run
            try:
                self.assertTrue(
                    self.mod.installed_version_matches(target_path, release)
                )
            finally:
                self.mod.subprocess.run = original_run

    def test_run_install_rejects_mismatched_asset_digest_before_extraction(self):
        payload = b"wrong compressed bytes"
        expected_digest = "sha256:" + hashlib.sha256(b"expected").hexdigest()
        asset = self.mod.ReleaseAsset(
            name="codex-aarch64-apple-darwin.zst",
            url="https://api.github.example/assets/1",
            browser_download_url="https://github.example/download",
            digest=expected_digest,
        )
        release = self.mod.Release(tag_name="rust-v0.136.0", assets=[asset])
        selected = self.mod.SelectedAsset(asset=asset, kind="zst")

        calls = {"extract": 0}

        def fail_if_called(*args, **kwargs):
            calls["extract"] += 1
            raise AssertionError("extract_executable should not run")

        patches = {
            "github_token": lambda: self.mod.AuthToken(None, "test"),
            "fetch_latest_release": lambda token: self.mod.ReleaseSelection(
                release=release, candidates_count=1
            ),
            "current_platform_target": lambda: self.mod.PlatformTarget(
                "aarch64-apple-darwin", "codex"
            ),
            "select_codex_asset": lambda release, target: selected,
            "xdg_bin_dir": lambda: Path(tempfile.gettempdir()) / "codex-test-bin",
            "state_status": lambda target_path, release, selected: "missing",
            "installed_version_matches": lambda target_path, release: False,
            "urlopen_bytes": lambda *args, **kwargs: payload,
            "extract_executable": fail_if_called,
        }
        originals = {name: getattr(self.mod, name) for name in patches}
        for name, replacement in patches.items():
            setattr(self.mod, name, replacement)
        try:
            with self.assertRaisesRegex(RuntimeError, "digest"):
                self.mod.run_install(self.mod.InstallSpec())
            self.assertEqual(calls["extract"], 0)
        finally:
            for name, original in originals.items():
                setattr(self.mod, name, original)


if __name__ == "__main__":
    unittest.main()
