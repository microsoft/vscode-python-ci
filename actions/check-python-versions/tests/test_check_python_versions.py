# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import contextlib
import datetime
import importlib.util
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import yaml


ACTION = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "checker", ACTION / "scripts" / "check_python_versions.py"
)
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)
NOW = datetime.datetime(2026, 8, 10, tzinfo=datetime.timezone.utc)


def release(name="Python 3.15.0rc1", date="2026-08-01T12:00:00Z", **overrides):
    return {
        "name": name,
        "release_date": date,
        "is_published": True,
        "pre_release": True,
        "version": 3,
        **overrides,
    }


def files_input(path, key="python"):
    return yaml.safe_dump([{"path": str(path), "key": key}])


class ReleaseTests(unittest.TestCase):
    def test_selects_newest_released_series_numerically(self):
        releases = [
            release("Python 3.9.0rc9"),
            release("Python 3.14.0rc2"),
            release("Python 3.15.0rc1"),
            release("Python 3.16.0rc1", "2027-08-01T00:00:00Z"),
            release("Python 3.16.0b1"),
            release("Python 3.16.0"),
            release("Python 3.16.0rc1", is_published=False),
            release("Python 3.16.0rc1", pre_release=False),
            release("Python 3.16.0rc1", version=2),
            None,
        ]
        self.assertEqual(checker.latest_release_candidate(releases, NOW), "3.15")

    def test_rejects_invalid_response_and_absent_candidates(self):
        for releases in ({}, [], [release("Python 3.16.0b1")]):
            with self.subTest(releases=releases), self.assertRaises(ValueError):
                checker.latest_release_candidate(releases, NOW)

    def test_rejects_invalid_or_timezone_free_candidate_dates(self):
        for date in ("invalid", "2026-08-01T12:00:00", None):
            with self.subTest(date=date), self.assertRaises(ValueError):
                checker.latest_release_candidate([release(date=date)], NOW)

    def test_fetch_uses_timeout_and_decodes_response(self):
        with mock.patch.object(checker.urllib.request, "urlopen") as fetch:
            fetch.return_value.__enter__.return_value = io.StringIO(
                json.dumps([release()])
            )
            self.assertEqual(checker.fetch_releases(), [release()])
            self.assertEqual(fetch.call_args.kwargs["timeout"], 30)
            self.assertEqual(fetch.call_args.args[0].full_url, checker.DOWNLOADS_URL)


class MatrixTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name).resolve()
        self.workflow = self.root / "workflow.yml"

    def write_matrix(self, matrix):
        self.workflow.write_text(
            "jobs:\n  test:\n    strategy:\n      matrix:\n"
            + "".join(f"        {line}\n" for line in matrix.splitlines()),
            encoding="utf-8",
        )

    def test_fixture_preserves_unquoted_versions_and_ignores_unrelated_jobs(self):
        workflow = ACTION / "tests" / "fixtures" / "workflow.yml"
        self.assertEqual(
            checker.configured_matrices(workflow, "python"),
            [("test", {"3.10", "3.14", "3.15"})],
        )
        self.assertEqual(
            checker.configured_matrices(workflow, "python-version"),
            [("integration", {"3.10", "3.15"})],
        )

    def test_reads_only_the_requested_custom_key(self):
        self.write_matrix(
            "versions: ['3.10', '3.15']\npython: '${{ inputs.python }}'"
        )
        self.assertEqual(
            checker.configured_matrices(self.workflow, "versions"),
            [("test", {"3.10", "3.15"})],
        )
        with self.assertRaises(ValueError):
            checker.configured_matrices(self.workflow, "missing-key")

    def test_normalizes_patch_prerelease_and_dev_versions(self):
        self.write_matrix(
            "python: ['3.10.12', '3.11.0a1', '3.12.0b2', '3.13.0rc1', "
            "'3.14.0.dev1', '3.15-dev', '3.x']"
        )
        self.assertEqual(
            checker.configured_matrices(self.workflow, "python"),
            [("test", {"3.10", "3.11", "3.12", "3.13", "3.14", "3.15"})],
        )

    def test_reports_each_missing_explicit_matrix(self):
        self.workflow.write_text(
            "jobs:\n"
            "  unit:\n    strategy:\n      matrix:\n        python: ['3.14', '3.15']\n"
            "  integration:\n    strategy:\n      matrix:\n        python-version: ['3.14']\n"
            "  floating:\n    strategy:\n      matrix:\n        python: ['3.x']\n",
            encoding="utf-8",
        )
        workflows = [
            (self.workflow, key, checker.configured_matrices(self.workflow, key))
            for key in ("python", "python-version")
        ]
        self.assertEqual(
            checker.missing_matrices("3.15", workflows, self.root),
            [{"file": "workflow.yml", "job": "integration", "key": "python-version"}],
        )
        self.assertEqual(checker.missing_matrices("3.14", workflows, self.root), [])

    def test_rejects_unsupported_relevant_matrices(self):
        cases = [
            "python: []",
            "python: ['3.x']",
            "python: \"${{ fromJSON(needs.generate.outputs.versions) }}\"",
            "python: ['3.14', '${{ inputs.python }}']",
            "python: ['3.15']\ninclude:\n  - os: ubuntu-latest",
            "python: ['3.15']\nexclude:\n  - python: '3.15'",
            "include:\n  - python: '3.15'",
            "python: ['unknown']",
            "python: [{version: '3.15'}]",
        ]
        for matrix in cases:
            with self.subTest(matrix=matrix):
                self.write_matrix(matrix)
                with self.assertRaises(ValueError):
                    checker.configured_matrices(self.workflow, "python")

    def test_rejects_dynamic_matrix_and_missing_jobs(self):
        for text in (
            "jobs:\n  test:\n    strategy:\n      matrix: '${{ needs.generate.outputs.matrix }}'",
            "jobs: []",
            "",
        ):
            with self.subTest(text=text):
                self.workflow.write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError):
                    checker.configured_matrices(self.workflow, "python")

    def test_inputs_are_relative_files_with_keys_and_duplicate_pairs_are_ignored(self):
        self.write_matrix("python: ['3.15']")
        files = """
- path: workflow.yml
  key: python
- path: workflow.yml
  key: python
- path: workflow.yml
  key: python-version
"""
        self.assertEqual(
            checker.parse_files(files, self.root),
            (self.root, [(self.workflow, "python"), (self.workflow, "python-version")]),
        )
        for path in (str(self.workflow), ".", "../outside.yml", "missing.yml"):
            with self.subTest(path=path), self.assertRaises((ValueError, OSError)):
                checker.parse_files(files_input(path), self.root)

    def test_rejects_missing_or_invalid_file_keys(self):
        self.write_matrix("python: ['3.15']")
        for files in (
            "",
            "[]",
            "workflow.yml",
            "- workflow.yml",
            "- path: workflow.yml",
            "- {path: workflow.yml, key: ''}",
            "- {path: workflow.yml, key: []}",
            "- {path: [], key: python}",
            "- {path: workflow.yml, key: python, extra: value}",
        ):
            with self.subTest(files=files), self.assertRaises(ValueError):
                checker.parse_files(files, self.root)

    def test_rejects_existing_file_outside_checkout(self):
        checkout = self.root / "checkout"
        checkout.mkdir()
        (self.root / "outside.yml").write_text("jobs: {}", encoding="utf-8")
        with self.assertRaises(ValueError):
            checker.parse_files(files_input("../outside.yml"), checkout)

    def test_rejects_symlink_escaping_checkout(self):
        with tempfile.TemporaryDirectory() as outside:
            target = pathlib.Path(outside) / "outside.yml"
            target.write_text("jobs: {}", encoding="utf-8")
            link = self.root / "link.yml"
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("Symlink creation is not available on this runner")
            with self.assertRaises(ValueError):
                checker.parse_files(files_input("link.yml"), self.root)


class IssueTests(unittest.TestCase):
    def setUp(self):
        self.missing = [
            {"file": ".github/workflows/pr-check.yml", "job": "test", "key": "python"}
        ]

    def test_creates_issue_with_missing_jobs_and_labels(self):
        with mock.patch.object(
            checker.subprocess, "run",
            return_value=mock.Mock(stdout="https://github.com/owner/repo/issues/1\n"),
        ) as gh:
            url = checker.create_issue(
                "owner/repo", "3.15", self.missing, "debt, python-version", "test-token"
            )
        self.assertEqual(url, "https://github.com/owner/repo/issues/1")
        gh.assert_called_once()
        arguments = gh.call_args.args[0]
        self.assertEqual(arguments[:3], ["gh", "issue", "create"])
        body = arguments[arguments.index("--body") + 1]
        self.assertIn(".github/workflows/pr-check.yml", body)
        self.assertIn("job `test`", body)
        self.assertIn("key `python`", body)
        self.assertIn("build-runtime pins unchanged", body)
        self.assertEqual(arguments[-4:], ["--label", "debt", "--label", "python-version"])
        self.assertNotIn("test-token", arguments)
        self.assertEqual(gh.call_args.kwargs["env"]["GH_TOKEN"], "test-token")
        self.assertTrue(gh.call_args.kwargs["check"])
        self.assertNotIn("shell", gh.call_args.kwargs)

    def test_failed_creation_raises(self):
        with mock.patch.object(
            checker.subprocess, "run",
            side_effect=subprocess.CalledProcessError(1, ["gh", "issue", "create"]),
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                checker.create_issue("owner/repo", "3.15", self.missing, "", "test-token")


class EntryPointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name).resolve()
        self.env = {
            "GITHUB_WORKSPACE": str(ACTION),
            "CHECK_FILES": """
- path: tests/fixtures/workflow.yml
  key: python
- path: tests/fixtures/workflow.yml
  key: python-version
""",
            "CHECK_CREATE_ISSUE": "false",
            "GITHUB_OUTPUT": str(self.root / "outputs"),
            "GITHUB_STEP_SUMMARY": str(self.root / "summary"),
        }

    def test_check_only_publishes_missing_coverage_without_github_calls(self):
        with mock.patch.dict(os.environ, self.env, clear=True):
            with mock.patch.object(checker, "fetch_releases", return_value=[release("Python 3.16.0rc1")]):
                with mock.patch.object(checker, "create_issue") as issue:
                    with contextlib.redirect_stdout(io.StringIO()):
                        checker.main()
        issue.assert_not_called()
        outputs = dict(
            line.split("=", 1)
            for line in (self.root / "outputs").read_text(encoding="utf-8").splitlines()
        )
        self.assertEqual(outputs["latest-version"], "3.16")
        self.assertEqual(outputs["issue-url"], "")
        self.assertEqual(
            [(item["job"], item["key"]) for item in json.loads(outputs["missing-matrices"])],
            [("test", "python"), ("integration", "python-version")],
        )
        self.assertIn("Missing declared coverage", (self.root / "summary").read_text())

    def test_covered_issue_mode_does_not_call_github(self):
        self.env.update(CHECK_CREATE_ISSUE="true", CHECK_TOKEN="test-token")
        with mock.patch.dict(os.environ, self.env, clear=True):
            with mock.patch.object(checker, "fetch_releases", return_value=[release()]):
                with mock.patch.object(checker, "create_issue") as issue:
                    with contextlib.redirect_stdout(io.StringIO()):
                        checker.main()
        issue.assert_not_called()
        self.assertIn("missing-matrices=[]", (self.root / "outputs").read_text())

    def test_issue_mode_publishes_issue_url(self):
        self.env.update(
            CHECK_CREATE_ISSUE="true", CHECK_TOKEN="test-token", GITHUB_REPOSITORY="owner/repo"
        )
        with mock.patch.dict(os.environ, self.env, clear=True):
            with mock.patch.object(checker, "fetch_releases", return_value=[release("Python 3.16.0rc1")]):
                with mock.patch.object(checker, "create_issue", return_value="https://github.com/issue/1"):
                    with contextlib.redirect_stdout(io.StringIO()):
                        checker.main()
        self.assertIn("issue-url=https://github.com/issue/1", (self.root / "outputs").read_text())

    def test_validates_inputs_before_network_and_does_not_publish_on_failure(self):
        for overrides in (
            {"CHECK_CREATE_ISSUE": "yes"},
            {"CHECK_CREATE_ISSUE": "true"},
            {"CHECK_FILES": files_input("missing.yml")},
        ):
            with self.subTest(overrides=overrides):
                with mock.patch.dict(os.environ, {**self.env, **overrides}, clear=True):
                    with mock.patch.object(checker, "fetch_releases") as fetch:
                        with self.assertRaises((ValueError, OSError)):
                            checker.main()
                        fetch.assert_not_called()
        self.assertFalse((self.root / "outputs").exists())

    def test_network_or_issue_failure_does_not_publish_success(self):
        self.env.update(
            CHECK_CREATE_ISSUE="true", CHECK_TOKEN="test-token", GITHUB_REPOSITORY="owner/repo"
        )
        with mock.patch.dict(os.environ, self.env, clear=True):
            with mock.patch.object(
                checker, "fetch_releases", side_effect=checker.urllib.error.URLError("offline")
            ):
                with self.assertRaises(checker.urllib.error.URLError):
                    checker.main()
            with mock.patch.object(checker, "fetch_releases", return_value=[release("Python 3.16.0rc1")]):
                with mock.patch.object(
                    checker, "create_issue", side_effect=subprocess.CalledProcessError(1, ["gh"])
                ):
                    with self.assertRaises(subprocess.CalledProcessError):
                        checker.main()
        self.assertFalse((self.root / "outputs").exists())
        self.assertFalse((self.root / "summary").exists())

    def test_cli_failure_is_nonzero_without_success_outputs(self):
        result = subprocess.run(
            [sys.executable, str(ACTION / "scripts" / "check_python_versions.py")],
            env={**os.environ, **self.env, "CHECK_FILES": files_input("missing.yml")},
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Python version check failed", result.stderr)
        self.assertFalse((self.root / "outputs").exists())

    def test_action_maps_outputs_and_passes_inputs_through_environment(self):
        action = yaml.load((ACTION / "action.yml").read_text(), Loader=yaml.BaseLoader)
        step = next(step for step in action["runs"]["steps"] if step.get("id") == "check")
        self.assertEqual(
            step["env"]["CHECK_FILES"], "${{ inputs.files }}"
        )
        for output in ("latest-version", "missing-matrices", "issue-url"):
            self.assertEqual(
                action["outputs"][output]["value"], f"${{{{ steps.check.outputs.{output} }}}}"
            )
        self.assertNotIn("${{ inputs.", step["run"])


if __name__ == "__main__":
    unittest.main()
