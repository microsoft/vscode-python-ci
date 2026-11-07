# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ACTION = Path(__file__).resolve().parents[1]
GETTER = ACTION.parent / "get-extension-version"
SPEC = importlib.util.spec_from_file_location(
    "release_pr", ACTION / "scripts" / "release_pr.py"
)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


def manifest(version, **values):
    return json.dumps({"name": "extension", "version": version, **values})


def yaml_command(name, action=ACTION):
    step = (
        (action / "action.yml")
        .read_text(encoding="utf-8")
        .split(f"    - name: {name}\n", 1)[1]
        .split("    - name:", 1)[0]
    )
    return textwrap.dedent(step.split("      run: |\n", 1)[1])


class ValidationTests(unittest.TestCase):
    def test_only_top_level_version_may_change(self):
        before = '{"version":"1.43.0","nested":{"version":"keep","x":[true,1]}}'
        after = '{"nested":{"x":[true,1.0],"version":"keep"},"version":"1.45.0"}'
        self.assertEqual(release.validate_change(before, after), "1.45.0")
        for values in (
            '{"version":"changed","x":[true,1]}',
            '{"version":"keep","x":[1,1]}',
            '{"version":"keep","x":[true,1.000000000000000000001]}',
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                release.validate_change(
                    before, '{"version":"1.45.0","nested":' + values + "}"
                )

    def test_version_upgrade_rules(self):
        for before, after in (
            ("2026.7.0-dev", "2026.9.0-dev"),
            ("1.43.0", "1.49.0"),
            ("1.45.0-rc.9", "1.45.0-rc.10"),
        ):
            with self.subTest(after=after):
                self.assertEqual(
                    release.validate_change(manifest(before), manifest(after)),
                    after,
                )
        for after in ("1.41.0", "1.44.0", "1.43.0+build", "invalid"):
            with self.subTest(after=after), self.assertRaises(ValueError):
                release.validate_change(manifest("1.43.0"), manifest(after))

    def test_ordinary_changes_return_nothing(self):
        before = manifest("1.43.0", dependency="old")
        after = manifest("1.43.0", dependency="new")
        self.assertIsNone(release.validate_change(before, after))

    def test_release_serialization_rejects_lossy_numbers(self):
        with self.assertRaises(ValueError):
            release.serialize_release(
                '{"version":"1.45.0","x":1.000000000000000000001}', "1.44.0"
            )


class GitWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="release action ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / "remote.git"
        self.work = self.root / "work"
        self.snapshots = self.root / "snapshots"
        self.work.mkdir()
        self.snapshots.mkdir()
        self.environment = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Release tests",
            "GIT_AUTHOR_EMAIL": "tests@example.invalid",
            "GIT_COMMITTER_NAME": "Release tests",
            "GIT_COMMITTER_EMAIL": "tests@example.invalid",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "ACTION_PATH": ACTION.as_posix(),
            "RUNNER_TEMP": self.snapshots.as_posix(),
        }
        self.git("init", "--bare", str(self.remote))
        self.git("init", "--initial-branch=main")
        self.git("remote", "add", "origin", str(self.remote))
        self.package = {
            "name": "extension",
            "version": "1.45.0",
            "nested": {"version": "keep"},
        }
        self.commit(
            {
                "package.json": manifest("1.43.0", nested={"version": "keep"}),
                "README.md": "before",
            }
        )
        self.git("checkout", "-b", "proposal")
        self.head = self.commit({"package.json": json.dumps(self.package)})
        self.git("checkout", "main")
        self.base = self.commit({"README.md": "target update"})
        self.git("push", "origin", "main", "proposal")
        git_path = Path(shutil.which("git"))
        self.bash = (
            str(git_path.parents[1] / "bin" / "bash.exe")
            if os.name == "nt"
            else shutil.which("bash")
        )

    def git(self, *args):
        return subprocess.run(
            ["git", *args],
            cwd=self.work,
            env=self.environment,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    def commit(self, files):
        for name, text in files.items():
            path = self.work / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        self.git("add", "--all")
        self.git("commit", "-m", "Test fixture")
        return self.git("rev-parse", "HEAD")

    def merge(self):
        self.git("checkout", "main")
        self.git("merge", "--no-ff", "proposal", "-m", "Merge release PR")
        self.git("push", "origin", "main")
        return self.git("rev-parse", "HEAD")

    def step(self, name, action=ACTION):
        output = self.root / "outputs"
        output.write_text("", encoding="utf-8")
        result = subprocess.run(
            [
                self.bash,
                "--noprofile",
                "--norc",
                "-e",
                "-o",
                "pipefail",
                "-c",
                yaml_command(name, action),
            ],
            cwd=self.work,
            env={
                **self.environment,
                "ACTION_PATH": action.as_posix(),
                "GITHUB_OUTPUT": output.as_posix(),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(f"{name}: {result.stdout}{result.stderr}")
        return dict(
            line.split("=", 1)
            for line in output.read_text(encoding="utf-8").splitlines()
        )

    def run_action(self, mode, source):
        self.git("checkout", "--detach", source)
        self.environment.update(BASE_SHA=self.base)
        self.step("Fetch the recorded base")
        if self.step("Check for a manifest-only change")["changed"] == "false":
            return None
        self.step("Check manifest file modes")
        self.step("Find the comparison base")
        self.step("Read the base manifest")
        self.step("Read the source manifest")
        version = self.step("Validate the manifest change").get("version")
        if not version:
            return None
        self.environment["PACKAGE_JSON_PATH"] = (
            self.snapshots / "release-pr.after.json"
        ).as_posix()
        self.environment.update(
            VERSION_TYPE="release",
            VERSION_STRATEGY="odd-even-minor",
            VERSION_MODE="previous",
            PRE_RELEASE_SUFFIX="",
        )
        stable = self.step("Get the extension version", GETTER)["version"]
        if mode == "release":
            self.environment["VERSION"] = stable
            self.step("Prepare the stable manifest")
            self.step("Stage the stable manifest")
            self.step("Commit the stable manifest")
            self.step("Push the finished release branch")
        return stable if mode == "release" else version

    def test_plan_is_read_only_and_release_preserves_merged_source(self):
        self.assertEqual(self.run_action("plan", self.head), "1.45.0")
        self.assertEqual(self.git("rev-parse", "HEAD"), self.head)
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(
            self.git(
                "--git-dir", str(self.remote), "for-each-ref", "refs/heads/release"
            ),
            "",
        )

        merged = self.merge()
        self.assertEqual(self.run_action("release", merged), "1.44.0")
        remote = ("--git-dir", str(self.remote))
        ref = "refs/heads/release/1.44.0"
        self.assertEqual(
            json.loads(self.git(*remote, "show", f"{ref}:package.json")),
            {**self.package, "version": "1.44.0"},
        )
        self.assertEqual(self.git(*remote, "show", f"{ref}:README.md"), "target update")
        self.assertEqual(self.git(*remote, "rev-parse", f"{ref}^"), merged)
        self.assertEqual(self.git(*remote, "rev-parse", "main"), merged)

    def test_existing_release_branch_is_never_overwritten(self):
        merged = self.merge()
        remote = ("--git-dir", str(self.remote))
        ref = "refs/heads/release/1.44.0"
        self.git(*remote, "update-ref", ref, self.base)
        with self.assertRaisesRegex(RuntimeError, "Push the finished release branch"):
            self.run_action("release", merged)
        self.assertEqual(self.git(*remote, "rev-parse", ref), self.base)
        self.assertEqual(self.git(*remote, "rev-parse", "main"), merged)

    def test_mixed_file_rebase_skips_before_json_comparison(self):
        self.git("checkout", "proposal")
        self.commit({Path("api") / "package.json": manifest("1.0.0")})
        self.commit({"package.json": manifest("1.47.0", nested={"version": "keep"})})
        self.git("rebase", "main")
        self.git("checkout", "main")
        self.git("merge", "--ff-only", "proposal")
        self.git("push", "origin", "main")
        source = self.git("rev-parse", "HEAD")
        self.assertIsNone(self.run_action("release", source))
        self.assertFalse((self.snapshots / "release-pr.before.json").exists())
        self.assertEqual(
            self.git(
                "--git-dir", str(self.remote), "for-each-ref", "refs/heads/release"
            ),
            "",
        )

    def test_mode_change_is_rejected_before_json_comparison(self):
        self.git("checkout", "proposal")
        self.git("update-index", "--chmod=+x", "package.json")
        self.git("commit", "-m", "Change manifest mode")
        with self.assertRaisesRegex(RuntimeError, "Check manifest file modes"):
            self.run_action("plan", self.git("rev-parse", "HEAD"))
        self.assertFalse((self.snapshots / "release-pr.before.json").exists())


if __name__ == "__main__":
    unittest.main()
