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
            "REPOSITORY": "owner/extension",
            "AUTHOR": "pr-creator",
            "AUTHOR_PERMISSION": "write",
            "AUTHOR_API_EXIT_CODE": "0",
            "RELEASE_BRANCH_PREFIX": "release/",
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
            str(
                next(
                    parent / "bin" / "bash.exe"
                    for parent in git_path.parents
                    if (parent / "bin" / "bash.exe").is_file()
                )
            )
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
        command = yaml_command(name, action)
        if name == "Check release author permissions":
            command = (
                "gh() {\n"
                '  printf "%s\\n" "$*" > "$RUNNER_TEMP/author-api-call"\n'
                '  printf "%s\\n" "$AUTHOR_PERMISSION"\n'
                '  return "$AUTHOR_API_EXIT_CODE"\n'
                "}\n" + command
            )
        result = subprocess.run(
            [
                self.bash,
                "--noprofile",
                "--norc",
                "-e",
                "-o",
                "pipefail",
                "-c",
                command,
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
        self.step("Check release author permissions")
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
        self.environment["VERSION"] = stable
        self.branch = self.step("Determine the release branch")["branch"]
        self.environment["RELEASE_BRANCH"] = self.branch
        if mode == "release":
            self.step("Prepare the stable manifest")
            self.step("Stage the stable manifest")
            self.step("Commit the stable manifest")
            self.step("Push the finished release branch")
        return stable if mode == "release" else version

    def test_release_author_permission_allowlist_and_pr_identity(self):
        for permission in ("write", "maintain", "admin"):
            with self.subTest(permission=permission):
                self.environment["AUTHOR_PERMISSION"] = permission
                self.step("Check release author permissions")
                self.assertEqual(
                    (self.snapshots / "author-api-call").read_text(encoding="utf-8"),
                    "api repos/owner/extension/collaborators/pr-creator/permission --jq .permission\n",
                )
        for permission in ("read", "triage", "none", "", "null", "unknown"):
            with self.subTest(permission=permission):
                self.environment["AUTHOR_PERMISSION"] = permission
                with self.assertRaisesRegex(RuntimeError, "author must have write"):
                    self.step("Check release author permissions")

    def test_unauthorized_or_failed_lookup_rejects_both_modes_before_writes(self):
        merged = self.merge()
        remote = ("--git-dir", str(self.remote))
        refs = self.git(*remote, "show-ref")
        for permission, exit_code in (("read", "0"), ("write", "1")):
            for mode, source in (("plan", self.head), ("release", merged)):
                with self.subTest(
                    permission=permission, exit_code=exit_code, mode=mode
                ):
                    self.environment.update(
                        AUTHOR_PERMISSION=permission, AUTHOR_API_EXIT_CODE=exit_code
                    )
                    with self.assertRaisesRegex(
                        RuntimeError, "Check release author permissions"
                    ):
                        self.run_action(mode, source)
                    self.assertEqual(self.git("rev-parse", "HEAD"), source)
                    self.assertEqual(self.git("status", "--porcelain"), "")
                    self.assertEqual(self.git(*remote, "show-ref"), refs)

    def test_unchanged_version_skips_authorization(self):
        self.git("checkout", "proposal")
        head = self.commit(
            {
                "package.json": manifest(
                    "1.43.0", nested={"version": "keep"}, description="ordinary edit"
                )
            }
        )
        merged = self.merge()
        self.environment.update(AUTHOR_PERMISSION="read", AUTHOR_API_EXIT_CODE="1")
        for mode, source in (("plan", head), ("release", merged)):
            with self.subTest(mode=mode):
                self.assertIsNone(self.run_action(mode, source))
                self.assertFalse((self.snapshots / "author-api-call").exists())
                self.assertEqual(self.git("status", "--porcelain"), "")

    def test_plan_is_read_only_and_release_preserves_merged_source(self):
        self.assertEqual(self.run_action("plan", self.head), "1.45.0")
        self.assertEqual(self.branch, "release/1.44.0")
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

    def test_custom_prefix_is_reported_in_plan_and_used_for_release(self):
        self.environment["RELEASE_BRANCH_PREFIX"] = "stable/v"
        self.assertEqual(self.run_action("plan", self.head), "1.45.0")
        self.assertEqual(self.branch, "stable/v1.44.0")
        self.assertEqual(self.git("rev-parse", "HEAD"), self.head)
        self.assertEqual(self.git("status", "--porcelain"), "")
        remote = ("--git-dir", str(self.remote))
        self.assertEqual(self.git(*remote, "for-each-ref", "refs/heads/stable"), "")

        merged = self.merge()
        self.assertEqual(self.run_action("release", merged), "1.44.0")
        self.assertEqual(self.branch, "stable/v1.44.0")
        ref = f"refs/heads/{self.branch}"
        self.assertEqual(
            json.loads(self.git(*remote, "show", f"{ref}:package.json")),
            {**self.package, "version": "1.44.0"},
        )
        self.assertEqual(self.git(*remote, "rev-parse", f"{ref}^"), merged)
        self.assertEqual(self.git(*remote, "rev-parse", "main"), merged)
        self.assertEqual(self.git(*remote, "for-each-ref", "refs/heads/release"), "")

    def test_invalid_prefix_fails_before_writing_in_both_modes(self):
        merged = self.merge()
        remote = ("--git-dir", str(self.remote))
        refs = self.git(*remote, "show-ref")
        for prefix in ("bad prefix/", "release/../", "release\n/", "release/:main"):
            for mode, source in (("plan", self.head), ("release", merged)):
                with self.subTest(prefix=prefix, mode=mode):
                    self.environment["RELEASE_BRANCH_PREFIX"] = prefix
                    with self.assertRaisesRegex(RuntimeError, "Invalid release branch"):
                        self.run_action(mode, source)
                    self.assertEqual(self.git("rev-parse", "HEAD"), source)
                    self.assertEqual(self.git("status", "--porcelain"), "")
                    self.assertEqual(self.git(*remote, "show-ref"), refs)
                    self.assertEqual(
                        (self.root / "outputs").read_text(encoding="utf-8"), ""
                    )

    def test_existing_release_branch_is_never_overwritten(self):
        merged = self.merge()
        remote = ("--git-dir", str(self.remote))
        for prefix in ("release/", "stable/v"):
            with self.subTest(prefix=prefix):
                self.environment["RELEASE_BRANCH_PREFIX"] = prefix
                ref = f"refs/heads/{prefix}1.44.0"
                self.git(*remote, "update-ref", ref, self.base)
                with self.assertRaisesRegex(
                    RuntimeError, "Push the finished release branch"
                ):
                    self.run_action("release", merged)
                self.assertEqual(self.git(*remote, "rev-parse", ref), self.base)
                self.assertEqual(self.git(*remote, "rev-parse", "main"), merged)

    def test_existing_identical_release_branch_fails(self):
        merged = self.merge()
        remote = ("--git-dir", str(self.remote))
        for prefix in ("release/", "stable/v"):
            with self.subTest(prefix=prefix):
                self.environment["RELEASE_BRANCH_PREFIX"] = prefix
                self.assertEqual(self.run_action("release", merged), "1.44.0")
                ref = f"refs/heads/{prefix}1.44.0"
                prepared = self.git("rev-parse", "HEAD")
                self.assertEqual(self.git(*remote, "rev-parse", ref), prepared)
                with self.assertRaisesRegex(
                    RuntimeError, "Release branch already exists"
                ):
                    self.step("Push the finished release branch")
                self.assertEqual(self.git(*remote, "rev-parse", ref), prepared)
                self.assertEqual(self.git(*remote, "rev-parse", "main"), merged)

    def test_plan_rejects_lossy_serialization_without_writing(self):
        before = '{"version":"1.43.0","x":1.000000000000000000001}'
        after = before.replace("1.43.0", "1.45.0")
        self.git("checkout", "-b", "precision")
        self.base = self.commit({"package.json": before})
        head = self.commit({"package.json": after})
        self.git("push", "origin", "precision")
        with self.assertRaisesRegex(RuntimeError, "Serializing package.json"):
            self.run_action("plan", head)
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(
            (self.work / "package.json").read_text(encoding="utf-8"), after
        )
        self.assertEqual((self.root / "outputs").read_text(encoding="utf-8"), "")

    def test_mixed_file_rebase_skips_before_json_comparison(self):
        self.environment.update(AUTHOR_PERMISSION="read", AUTHOR_API_EXIT_CODE="1")
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
        self.assertFalse((self.snapshots / "author-api-call").exists())
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
