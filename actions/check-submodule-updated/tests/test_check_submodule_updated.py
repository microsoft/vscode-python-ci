# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def find_bash():
    if os.name == "nt":
        program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        git_bash = program_files / "Git" / "bin" / "bash.exe"
        if git_bash.exists():
            return str(git_bash)
    return shutil.which("bash") or "bash"


class SubmoduleFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="submodule action ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bash = find_bash()
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
            encoding="utf-8",
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

    def run_script(self, name, output, **environment):
        run_environment = {
            **self.environment,
            "GITHUB_OUTPUT": self.shell_path(output),
            **environment,
        }
        if "GITHUB_STEP_SUMMARY" in run_environment:
            run_environment["GITHUB_STEP_SUMMARY"] = self.shell_path(
                Path(run_environment["GITHUB_STEP_SUMMARY"])
            )
        return subprocess.run(
            [self.bash, self.shell_path(SCRIPTS / name)],
            cwd=self.consumer,
            env=run_environment,
            capture_output=True,
            encoding="utf-8",
        )

    def shell_path(self, path):
        if os.name != "nt":
            return str(path)
        return subprocess.run(
            [self.bash, "-c", 'cygpath -u "$1"', "cygpath", str(path)],
            capture_output=True,
            encoding="utf-8",
            check=True,
        ).stdout.strip()

    def read_outputs(self, path):
        return dict(
            line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines()
        )

    def run_action(self, **inputs):
        before = self.snapshot()
        pin_output = self.root / "pin-output"
        upstream_output = self.root / "upstream-output"
        output = self.root / "output"
        summary = self.root / "summary"
        for path in (pin_output, upstream_output, output, summary):
            path.write_text("", encoding="utf-8")

        inputs = {
            "path": self.path,
            "branch": "main",
            "fail-if-outdated": "true",
            **inputs,
        }
        pin = self.run_script(
            "read_pin.sh",
            pin_output,
            SUBMODULE_PATH=inputs["path"],
        )
        logs = pin.stdout + pin.stderr
        if pin.returncode != 0:
            result_code = pin.returncode
        else:
            pin_values = self.read_outputs(pin_output)
            upstream = self.run_script(
                "read_upstream.sh",
                upstream_output,
                SUBMODULE_COMMIT=pin_values["commit"],
                SUBMODULE_PATH=inputs["path"],
                SUBMODULE_BRANCH=inputs["branch"],
                GIT_TERMINAL_PROMPT="0",
            )
            logs += upstream.stdout + upstream.stderr
            if upstream.returncode != 0:
                result_code = upstream.returncode
            else:
                upstream_values = self.read_outputs(upstream_output)
                compare = self.run_script(
                    "compare.sh",
                    output,
                    GITHUB_STEP_SUMMARY=str(summary),
                    SUBMODULE_PATH=inputs["path"],
                    SUBMODULE_BRANCH=inputs["branch"],
                    PINNED_SHA=pin_values["pinned-sha"],
                    LATEST_SHA=upstream_values["sha"],
                )
                logs += compare.stdout + compare.stderr
                result_code = compare.returncode
                if (
                    result_code == 0
                    and self.read_outputs(output)["status"] == "outdated"
                    and inputs["fail-if-outdated"] != "false"
                ):
                    result_code = 1
                    logs += "Submodule pin is outdated.\n"

        self.assertEqual(self.snapshot(), before, "Action changed repository state")
        outputs = self.read_outputs(output)
        return (
            result_code,
            outputs,
            summary.read_text(encoding="utf-8"),
            logs,
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
        self.assertEqual(outputs, {}, logs)
        self.assertEqual(summary, "", logs)

    def test_uninitialized_outdated_report_only_with_spaces(self):
        self.assertFalse((self.consumer / self.path).exists())
        self.check("outdated", **{"fail-if-outdated": "false"})

    def test_unicode_module_name_and_path(self):
        self.git("config", "-f", ".gitmodules", "--remove-section", self.module)
        self.git("update-index", "--force-remove", "--", self.path)
        self.module = "submodule.Shared \u03bb module"
        self.path = "external/shared \u03bb library"
        self.git("config", "-f", ".gitmodules", f"{self.module}.path", self.path)
        self.git("config", "-f", ".gitmodules", f"{self.module}.url", str(self.upstream))
        self.pin(self.old_sha)
        self.environment["PYTHONUTF8"] = "0"
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

    def test_duplicate_committed_submodule_path_is_rejected(self):
        self.git("config", "-f", ".gitmodules", "submodule.decoy.path", self.path)
        self.git(
            "config",
            "-f",
            ".gitmodules",
            "submodule.decoy.url",
            str(self.root / "decoy remote"),
        )
        self.git("add", ".gitmodules")
        self.git("commit", "--quiet", "-m", "Add duplicate submodule path")
        self.check_failure()

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

    def test_directory_with_multiple_entries_is_not_a_submodule(self):
        (self.consumer / "external").mkdir()
        extra_file = self.consumer / "external" / "regular.txt"
        extra_file.write_text("not a submodule\n", encoding="utf-8")
        self.git("add", "external/regular.txt")
        self.git("commit", "--quiet", "-m", "Add another external entry")
        self.check_failure(path="external/")

    def test_missing_branch_fails_in_report_only_mode(self):
        self.check_failure(branch="missing-branch")

    def test_branch_pattern_is_not_accepted_as_an_exact_branch(self):
        self.check_failure(branch="mai*")

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
