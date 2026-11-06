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
SPEC = importlib.util.spec_from_file_location(
    "release_pr", ACTION / "scripts" / "release_pr.py"
)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


def manifest(version, **values):
    return json.dumps({"name": "extension", "version": version, **values})


def yaml_command(name):
    step = (
        (ACTION / "action.yml")
        .read_text(encoding="utf-8")
        .split(f"    - name: {name}\n", 1)[1]
        .split("    - name:", 1)[0]
    )
    return textwrap.dedent(step.split("      run: |\n", 1)[1])


class ValidationTests(unittest.TestCase):
    def test_all_extension_version_formats(self):
        for source, stable in {
            "2026.9.0-dev": "2026.8.0",
            "2026.13.0": "2026.12.0",
            "1.45.0": "1.44.0",
            "2027.1.9-rc.2+build.007": "2027.0.0",
            "2147483647.2147483647.0": "2147483647.2147483646.0",
        }.items():
            with self.subTest(source=source):
                self.assertEqual(
                    release.validate_change(manifest("0.1.0"), manifest(source)),
                    (source, stable),
                )
        for source in (
            "1.0.0",
            "1.44.0",
            "1.-1.0",
            "1.03.0",
            "1.3",
            "1.3.0-",
            "1.3.0-dev..1",
            "1.3.0-01",
            "1.3.0+",
            "1.3.0+bad+meta",
            "\u0661.3.0",
            "2147483648.3.0",
        ):
            with self.subTest(source=source), self.assertRaises(ValueError):
                release.validate_change(manifest("0.1.0"), manifest(source))

    def test_upgrade_precedence_not_textual_sorting(self):
        for before, after in (
            ("2026.9.0-dev", "2026.11.0-dev"),
            ("1.45.0-rc.9", "1.45.0-rc.10"),
            ("1.45.0-1", "1.45.0-dev"),
            ("1.45.0-dev", "1.45.0"),
            ("1.45.0-dev", "1.45.0-dev.1"),
        ):
            with self.subTest(before=before, after=after):
                self.assertLess(release.version_key(before), release.version_key(after))
        self.assertEqual(
            release.version_key("1.45.0+one"), release.version_key("1.45.0+two")
        )

    def test_semantic_json_comparison(self):
        before = '{"version":"1.43.0","nested":{"version":"keep","x":[true,1]}}'
        after = '{"nested":{"x":[true,1.0],"version":"keep"},"version":"1.45.0"}'
        self.assertEqual(release.validate_change(before, after), ("1.45.0", "1.44.0"))
        for values in (
            '{"version":"changed","x":[true,1]}',
            '{"version":"keep","x":[1,1]}',
            '{"version":"keep","x":[1,true]}',
            '{"version":"keep","x":[true,1.000000000000000000001]}',
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                release.validate_change(
                    before, '{"version":"1.45.0","nested":' + values + "}"
                )

    def test_invalid_json_and_duplicates_fail(self):
        for text in (
            '{"version":"1.43.0","version":"1.45.0"}',
            '{"version":"1.45.0","nested":{"x":1,"x":2}}',
            '{"version":"1.45.0","x":NaN}',
            '{"version":45}',
            '["1.45.0"]',
            "{}",
        ):
            with self.subTest(text=text), self.assertRaises((TypeError, ValueError)):
                release.parse_manifest(text)

    def test_ordinary_changes_return_nothing(self):
        before = manifest("1.43.0", dependency="old")
        after = manifest("1.43.0", dependency="new")
        self.assertIsNone(release.validate_change(before, after))

    def test_invalid_upgrades_fail(self):
        for after in ("1.41.0", "1.44.0", "1.43.0-rc.1", "1.43.0+build"):
            with self.subTest(after=after), self.assertRaises(ValueError):
                release.validate_change(manifest("1.43.0"), manifest(after))

    def test_stable_serialization_preserves_nested_values(self):
        text = '{"version":"1.45.0-dev","nested":{"version":"keep"},"title":"caf\\u00e9","x":1.0}'
        result = release.serialize_release(text, "1.44.0")
        self.assertEqual(
            json.loads(result),
            {
                "version": "1.44.0",
                "nested": {"version": "keep"},
                "title": "caf\u00e9",
                "x": 1.0,
            },
        )
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
        self.command("git", "init", "--bare", str(self.remote))
        self.original = {"package.json": (manifest("1.43.0", enabled=True), "100644")}
        self.fork = self.snapshot("fork", self.original)
        self.target = {**self.original, "README.md": ("target update", "100644")}
        self.base = self.snapshot("base", self.target, [self.fork])
        intermediate = self.snapshot(
            "first PR commit",
            {"package.json": (manifest("1.45.0-dev", enabled=True), "100644")},
            [self.fork],
        )
        self.proposed = {"package.json": (manifest("1.45.0", enabled=True), "100644")}
        self.head = self.snapshot("head", self.proposed, [intermediate])
        self.merged_files = {**self.target, **self.proposed}
        self.merged = self.snapshot("squash", self.merged_files, [self.base])
        self.git("update-ref", "refs/heads/main", self.merged)
        self.git("update-ref", "refs/heads/proposal", self.head)
        self.git("symbolic-ref", "HEAD", "refs/heads/main")
        self.command("git", "clone", str(self.remote), str(self.work))
        git_path = Path(shutil.which("git"))
        self.bash = (
            str(git_path.parents[1] / "bin" / "bash.exe")
            if os.name == "nt"
            else shutil.which("bash")
        )

    def command(self, *args, data=None, cwd=None):
        return subprocess.run(
            args,
            input=data,
            cwd=cwd,
            env=self.environment,
            capture_output=True,
            check=True,
        ).stdout

    def git(self, *args, data=None):
        return self.command("git", "--git-dir", str(self.remote), *args, data=data)

    def tree(self, files):
        entries = []
        directories = {}
        for path, (content, mode) in files.items():
            name, separator, rest = path.partition("/")
            if separator:
                directories.setdefault(name, {})[rest] = (content, mode)
            else:
                blob = self.git(
                    "hash-object", "-w", "--stdin", data=content.encode()
                ).strip()
                entries.append(mode.encode() + b" blob " + blob + b"\t" + name.encode())
        for name, contents in directories.items():
            entries.append(
                b"040000 tree " + self.tree(contents).encode() + b"\t" + name.encode()
            )
        return (
            self.git("mktree", "-z", data=b"".join(entry + b"\0" for entry in entries))
            .decode()
            .strip()
        )

    def snapshot(self, message, files, parents=()):
        args = ["commit-tree", self.tree(files)]
        for parent in parents:
            args.extend(("-p", parent))
        return self.git(*args, data=(message + "\n").encode()).decode().strip()

    def step(self, name):
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
                yaml_command(name),
            ],
            cwd=self.work,
            env={**self.environment, "GITHUB_OUTPUT": output.as_posix()},
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

    def run_action(self, mode="plan"):
        source = self.head if mode == "plan" else self.merged
        self.command("git", "fetch", "origin", source, cwd=self.work)
        self.command("git", "checkout", "--detach", source, cwd=self.work)
        self.environment.update(BASE_SHA=self.base, RELEASE_MODE=mode)
        self.step("Fetch the recorded base")
        if self.step("Check for a manifest-only change")["changed"] == "false":
            return None
        self.step("Check manifest file modes")
        self.step("Find the comparison base")
        self.step("Read the base manifest")
        self.step("Read the source manifest")
        version = self.step("Validate and prepare the manifest").get("version")
        if mode == "release" and version:
            self.environment["VERSION"] = version
            self.step("Stage the stable manifest")
            self.step("Commit the stable manifest")
            self.step("Push the finished release branch")
        return version

    def test_plan_uses_merge_base_and_returns_only_the_new_version(self):
        self.assertEqual(self.run_action(), "1.45.0")
        self.assertEqual(
            self.command("git", "rev-parse", "HEAD", cwd=self.work).decode().strip(),
            self.head,
        )
        self.assertEqual(
            self.command("git", "status", "--porcelain", cwd=self.work), b""
        )
        self.assertEqual(
            self.git("for-each-ref", "--format=%(refname)", "refs/heads/release"), b""
        )

    def test_all_merge_methods_preserve_target_changes_and_create_only_final_branch(
        self,
    ):
        for method in ("merge", "squash", "rebase"):
            with self.subTest(method=method):
                if method == "merge":
                    self.merged = self.snapshot(
                        method, self.merged_files, [self.base, self.head]
                    )
                elif method == "rebase":
                    earlier = self.snapshot(
                        "earlier rebased commit",
                        {
                            **self.target,
                            "package.json": (
                                manifest("1.45.0-dev", enabled=True),
                                "100644",
                            ),
                        },
                        [self.base],
                    )
                    self.merged = self.snapshot(method, self.merged_files, [earlier])
                else:
                    self.merged = self.snapshot(method, self.merged_files, [self.base])
                self.git("update-ref", "refs/heads/main", self.merged)
                self.assertEqual(self.run_action("release"), "1.44.0")
                ref = "refs/heads/release/1.44.0"
                self.assertEqual(self.git("show", f"{ref}:README.md"), b"target update")
                package = json.loads(self.git("show", f"{ref}:package.json"))
                self.assertEqual(
                    package, {"name": "extension", "version": "1.44.0", "enabled": True}
                )
                self.assertEqual(
                    self.git("show", "-s", "--format=%P", ref).decode().strip(),
                    self.merged,
                )
                self.assertEqual(
                    self.git("rev-parse", "main").decode().strip(), self.merged
                )
                self.git("update-ref", "-d", ref)

    def test_existing_branch_fails_without_modifying_it(self):
        self.assertEqual(self.run_action("release"), "1.44.0")
        ref = "refs/heads/release/1.44.0"
        previous = self.git("rev-parse", ref)
        with self.assertRaises(RuntimeError):
            self.run_action("release")
        self.assertEqual(self.git("rev-parse", ref), previous)

    def test_mixed_prs_and_rebases_skip_comparison(self):
        for path in ("other.txt", "api/package.json"):
            self.head = self.snapshot(
                "invalid PR", {**self.proposed, path: ("extra", "100644")}, [self.fork]
            )
            self.git("update-ref", "refs/heads/proposal", self.head)
            with self.subTest(path=path):
                self.assertIsNone(self.run_action())
                self.assertFalse((self.snapshots / "release-pr.before.json").exists())
        earlier = self.snapshot(
            "invalid earlier rebase",
            {**self.merged_files, "other.txt": ("extra", "100644")},
            [self.base],
        )
        self.merged = self.snapshot(
            "last rebase commit",
            {**self.merged_files, "other.txt": ("extra", "100644")},
            [earlier],
        )
        self.git("update-ref", "refs/heads/main", self.merged)
        self.assertIsNone(self.run_action("release"))
        self.assertFalse((self.snapshots / "release-pr.before.json").exists())
        self.assertEqual(
            self.git("for-each-ref", "--format=%(refname)", "refs/heads/release"), b""
        )

    def test_ordinary_dependency_changes_do_not_publish(self):
        package = manifest("1.43.0", enabled=False)
        self.head = self.snapshot(
            "dependencies", {"package.json": (package, "100644")}, [self.fork]
        )
        self.merged = self.snapshot(
            "merged dependencies",
            {**self.target, "package.json": (package, "100644")},
            [self.base],
        )
        self.git("update-ref", "refs/heads/proposal", self.head)
        self.git("update-ref", "refs/heads/main", self.merged)
        self.assertIsNone(self.run_action())
        self.assertIsNone(self.run_action("release"))
        self.assertEqual(
            self.git("for-each-ref", "--format=%(refname)", "refs/heads/release"), b""
        )

    def test_version_bump_with_other_json_changes_fails_without_publishing(self):
        package = manifest("1.45.0", enabled=False)
        self.head = self.snapshot(
            "invalid manifest", {"package.json": (package, "100644")}, [self.fork]
        )
        self.merged = self.snapshot(
            "merged invalid manifest",
            {**self.target, "package.json": (package, "100644")},
            [self.base],
        )
        self.git("update-ref", "refs/heads/proposal", self.head)
        self.git("update-ref", "refs/heads/main", self.merged)
        for mode in ("plan", "release"):
            with self.subTest(mode=mode), self.assertRaisesRegex(
                RuntimeError, "Only package.json's top-level version may change"
            ):
                self.run_action(mode)
            self.assertEqual(
                self.command("git", "status", "--porcelain", cwd=self.work), b""
            )
        self.assertEqual(
            self.git("for-each-ref", "--format=%(refname)", "refs/heads/release"), b""
        )

    def test_no_root_manifest_is_an_ordinary_pr(self):
        original = {"README.md": ("before", "100644")}
        self.base = self.snapshot("engineering base", original)
        self.head = self.snapshot(
            "engineering PR", {"README.md": ("after", "100644")}, [self.base]
        )
        self.git("update-ref", "refs/heads/main", self.base)
        self.git("update-ref", "refs/heads/proposal", self.head)
        self.assertIsNone(self.run_action())

    def test_manifest_metadata_changes_fail_before_comparison(self):
        for before_mode, after_mode in (
            (None, "100644"),
            ("100644", None),
            ("100644", "100755"),
            ("100644", "120000"),
            ("120000", "120000"),
        ):
            with self.subTest(before_mode=before_mode, after_mode=after_mode):
                before = (
                    {"package.json": (manifest("1.43.0"), before_mode)}
                    if before_mode
                    else {}
                )
                after = (
                    {"package.json": (manifest("1.45.0"), after_mode)}
                    if after_mode
                    else {}
                )
                self.base = self.snapshot("metadata base", before)
                self.head = self.snapshot("metadata PR", after, [self.base])
                self.git("update-ref", "refs/heads/proposal", self.head)
                with self.assertRaisesRegex(RuntimeError, "Check manifest file modes"):
                    self.run_action()
                self.assertFalse((self.snapshots / "release-pr.before.json").exists())


if __name__ == "__main__":
    unittest.main()
