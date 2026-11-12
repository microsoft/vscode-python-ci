# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml


ACTION = Path(__file__).resolve().parents[1]


class SubmoduleFreshnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.action = yaml.safe_load((ACTION / "action.yml").read_text(encoding="utf-8"))
        git_path = Path(shutil.which("git"))
        cls.bash = (
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

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="submodule action ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.upstream = self.root / "upstream library"
        self.consumer = self.root / "consumer repository"
        self.path = "external/shared library"
        self.module = "submodule.Different module name"
        self.environment = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
        for repository in (self.upstream, self.consumer):
            repository.mkdir()
            self.git("init", "--quiet", "--initial-branch=main", cwd=repository)
        self.git(
            "commit", "--quiet", "--allow-empty", "-m", "Initial", cwd=self.upstream
        )
        self.old_sha = self.git("rev-parse", "HEAD", cwd=self.upstream).strip()
        self.git("commit", "--quiet", "--allow-empty", "-m", "Latest", cwd=self.upstream)
        self.latest_sha = self.git("rev-parse", "HEAD", cwd=self.upstream).strip()
        self.git("config", "-f", ".gitmodules", f"{self.module}.path", self.path)
        self.git("config", "-f", ".gitmodules", f"{self.module}.url", str(self.upstream))
        self.pin(self.old_sha)

    def git(self, *args, cwd=None):
        return subprocess.run(
            ["git", *args],
            cwd=cwd or self.consumer,
            env=self.environment,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    def pin(self, sha):
        self.git("add", ".gitmodules")
        self.git("update-index", "--add", "--cacheinfo", f"160000,{sha},{self.path}")
        self.git("commit", "--quiet", "-m", "Pin shared library")

    def snapshot(self):
        state = [
            self.git(*args)
            for args in (
                ("rev-parse", "HEAD"),
                ("ls-files", "--stage"),
                ("status", "--porcelain"),
                ("diff", "--binary", "HEAD"),
                ("config", "--local", "--list"),
            )
        ]
        submodule = self.consumer / self.path
        state.extend((submodule.exists(), (submodule / ".git").exists()))
        if (submodule / ".git").exists():
            state.extend(
                (
                    self.git("rev-parse", "HEAD", cwd=submodule),
                    self.git("config", "--local", "--list", cwd=submodule),
                )
            )
        return state

    def run_action(self, **inputs):
        before = self.snapshot()
        values = {
            f"inputs.{name}": str(details.get("default", ""))
            for name, details in self.action["inputs"].items()
        }
        values.update({f"inputs.{name}": value for name, value in inputs.items()})
        values["github.workspace"] = str(self.consumer)

        # Only resolve the action's simple input/output/workspace references.
        def resolve(value):
            if value.startswith("${{") and value.endswith("}}"):
                return values.get(value[3:-2].strip(), "")
            return value

        summary = self.root / "summary"
        summary.write_text("", encoding="utf-8")
        logs = []
        for step in self.action["runs"]["steps"]:
            output = self.root / f"{step['id']}.output"
            output.write_text("", encoding="utf-8")
            environment = {
                **self.environment,
                **{name: resolve(value) for name, value in step.get("env", {}).items()},
                "GITHUB_OUTPUT": str(output),
                "GITHUB_STEP_SUMMARY": str(summary),
            }
            result = subprocess.run(
                [
                    self.bash,
                    "--noprofile",
                    "--norc",
                    "-e",
                    "-o",
                    "pipefail",
                    "-c",
                    step["run"],
                ],
                cwd=resolve(step.get("working-directory", "${{ github.workspace }}")),
                env=environment,
                capture_output=True,
                text=True,
            )
            logs.append(f"[{step['id']}]\n{result.stdout}{result.stderr}")
            for line in output.read_text(encoding="utf-8").splitlines():
                name, value = line.split("=", 1)
                values[f"steps.{step['id']}.outputs.{name}"] = value
            if result.returncode:
                break
        self.assertEqual(self.snapshot(), before, "Action changed repository state")
        outputs = {
            name: resolve(details["value"])
            for name, details in self.action["outputs"].items()
        }
        return (
            result.returncode,
            outputs,
            summary.read_text(encoding="utf-8"),
            "\n".join(logs),
        )

    def check(self, status, exit_code=0, pinned=None, latest=None, **inputs):
        code, outputs, summary, logs = self.run_action(path=self.path, **inputs)
        self.assertEqual(code, exit_code, logs)
        self.assertEqual(
            outputs,
            {
                "status": status,
                "pinned-sha": pinned or self.old_sha,
                "latest-sha": latest or self.latest_sha,
            },
            logs,
        )
        self.assertIn(f"Status: **{status}**", summary, logs)

    def check_failure(self, **inputs):
        inputs.setdefault("path", self.path)
        inputs["fail-if-outdated"] = "false"
        code, outputs, summary, logs = self.run_action(**inputs)
        self.assertNotEqual(code, 0, logs)
        self.assertEqual(outputs, {"status": "", "pinned-sha": "", "latest-sha": ""}, logs)
        self.assertEqual(summary, "", logs)

    def test_uninitialized_outdated_report_only_with_spaces(self):
        self.assertFalse((self.consumer / self.path).exists())
        self.check("outdated", **{"fail-if-outdated": "false"})

    def test_outdated_enforcement_preserves_outputs(self):
        self.check("outdated", exit_code=1, **{"fail-if-outdated": "true"})

    def test_outdated_enforcement_defaults_to_true(self):
        self.check("outdated", exit_code=1)

    def test_current_with_default_enforcement(self):
        self.pin(self.latest_sha)
        self.check("current", pinned=self.latest_sha)

    def test_exact_path_ignores_another_submodule_with_a_matching_suffix(self):
        self.git("config", "-f", ".gitmodules", "--remove-section", self.module)
        self.git(
            "config",
            "-f",
            ".gitmodules",
            "submodule.decoy.path",
            f"nested.path {self.path}",
        )
        self.git(
            "config",
            "-f",
            ".gitmodules",
            "submodule.decoy.url",
            str(self.root / "decoy remote"),
        )
        self.git("config", "-f", ".gitmodules", f"{self.module}.path", self.path)
        self.git("config", "-f", ".gitmodules", f"{self.module}.url", str(self.upstream))
        self.git(
            "update-index",
            "--add",
            "--cacheinfo",
            f"160000,{self.old_sha},nested.path {self.path}",
        )
        self.git("add", ".gitmodules")
        self.git("commit", "--quiet", "-m", "Add decoy before target submodule")
        self.check("outdated", **{"fail-if-outdated": "false"})

    def test_explicit_upstream_branch_overrides_main(self):
        self.pin(self.latest_sha)
        self.git("branch", "release", self.old_sha, cwd=self.upstream)
        self.check(
            "outdated",
            pinned=self.latest_sha,
            latest=self.old_sha,
            branch="release",
            **{"fail-if-outdated": "false"},
        )

    def test_committed_pin_and_config_override_index_and_submodule_checkout(self):
        self.pin(self.latest_sha)
        self.git(
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "update",
            "--init",
            "--",
            self.path,
        )
        self.git(
            "checkout", "--quiet", "--detach", self.old_sha,
            cwd=self.consumer / self.path,
        )
        self.git(
            "config",
            "-f",
            ".gitmodules",
            f"{self.module}.url",
            str(self.root / "missing remote"),
        )
        self.git("add", ".gitmodules", self.path)
        self.check("current", pinned=self.latest_sha)

    def test_missing_path_fails_in_report_only_mode(self):
        self.check_failure(path="missing")

    def test_regular_file_is_not_a_submodule(self):
        self.check_failure(path=".gitmodules")

    def test_missing_branch_fails_in_report_only_mode(self):
        self.check_failure(branch="missing-branch")

    def test_unavailable_upstream_fails_in_report_only_mode(self):
        self.git(
            "config",
            "-f",
            ".gitmodules",
            f"{self.module}.url",
            str(self.root / "missing remote"),
        )
        self.git("add", ".gitmodules")
        self.git("commit", "--quiet", "-m", "Use unavailable upstream")
        self.check_failure()

    def test_relative_url_fails_instead_of_checking_the_wrong_repository(self):
        self.git("config", "-f", ".gitmodules", f"{self.module}.url", "../relative-upstream")
        self.git("add", ".gitmodules")
        self.git("commit", "--quiet", "-m", "Use relative upstream")
        self.check_failure()


if __name__ == "__main__":
    unittest.main()
