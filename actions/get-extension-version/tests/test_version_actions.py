# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ACTION = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "extension_version", ACTION / "scripts" / "extension_version.py"
)
version = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(version)


class VersionActionTests(unittest.TestCase):
    def test_current_default_and_custom_paths_are_read_only(self):
        with tempfile.TemporaryDirectory(prefix="version actions ") as directory:
            root = Path(directory)
            for name in (
                "package.json",
                str(Path("nested space") / "custom.json"),
            ):
                with self.subTest(path=name):
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    original = (
                        b'{"version":"1.45.7-rc.1+build.2","nested":{"version":"keep"}}'
                    )
                    path.write_bytes(original)
                    output = root / "outputs"
                    arguments = ["--type=pre-release", "--strategy=odd-even-minor"]
                    if name != "package.json":
                        arguments = [
                            f"--package-json-path={name}",
                            "--mode=current",
                            "--type=release",
                            "--strategy=odd-even-minor",
                            "--pre-release-suffix=-invalid+suffix",
                        ]
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(ACTION / "scripts" / "extension_version.py"),
                            *arguments,
                        ],
                        cwd=root,
                        env={**os.environ, "GITHUB_OUTPUT": str(output)},
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    self.assertEqual(result.stdout.strip(), "1.45.7-rc.1+build.2")
                    self.assertEqual(
                        output.read_text(encoding="utf-8").splitlines()[-1],
                        "version=1.45.7-rc.1+build.2",
                    )
                    self.assertEqual(path.read_bytes(), original)

    def test_getter_rejects_missing_or_invalid_manifests(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "package.json"
            with self.assertRaises(FileNotFoundError):
                version.read_version(path)
            for text in (
                "{",
                "[]",
                "{}",
                '{"version":42}',
                '{"version":"1.2"}',
                '{"version":"1.2.3\\nextra=output"}',
                '{"version":"1.2.3","version":"1.2.4"}',
                '{"version":"1.2.3","value":NaN}',
            ):
                with self.subTest(text=text):
                    path.write_text(text, encoding="utf-8")
                    with self.assertRaises((ValueError, TypeError)):
                        version.read_version(path)

    def test_both_directions_and_minor_parities(self):
        for minor, kind, direction, expected in (
            (9, "pre-release", "next", 11),
            (9, "pre-release", "previous", 7),
            (9, "release", "next", 10),
            (9, "release", "previous", 8),
            (8, "pre-release", "next", 9),
            (8, "pre-release", "previous", 7),
            (8, "release", "next", 10),
            (8, "release", "previous", 6),
        ):
            with self.subTest(minor=minor, kind=kind, direction=direction):
                self.assertEqual(
                    version.calculate_version(
                        f"2026.{minor}.7-dev+build", kind, "odd-even-minor", direction
                    ),
                    f"2026.{expected}.0",
                )

    def test_suffix_handling(self):
        for suffix in ("", "dev", "rc.1"):
            with self.subTest(suffix=suffix):
                self.assertEqual(
                    version.calculate_version(
                        "1.45.0",
                        "pre-release",
                        "odd-even-minor",
                        "next",
                        pre_release_suffix=suffix,
                    ),
                    "1.47.0" + (f"-{suffix}" if suffix else ""),
                )
        self.assertEqual(
            version.calculate_version(
                "1.45.0-dev", "release", "odd-even-minor", "previous", "ignored+suffix"
            ),
            "1.44.0",
        )
        for suffix in ("-dev", "dev+build", "00", "rc..1", "dev\nextra=output"):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                version.calculate_version(
                    "1.45.0", "pre-release", "odd-even-minor", "next", suffix
                )

    def test_invalid_options_and_numeric_boundaries(self):
        for arguments in (
            ("1.45.0", "stable", "odd-even-minor", "next"),
            ("1.45.0", "release", "calendar", "next"),
            ("1.45.0", "release", "odd-even-minor", "back"),
            ("1.0.0", "release", "odd-even-minor", "previous"),
            ("1.0.0", "pre-release", "odd-even-minor", "previous"),
            ("1.1.0", "pre-release", "odd-even-minor", "previous"),
            ("1.2147483647.0", "release", "odd-even-minor", "next"),
            ("1.2147483647.0", "pre-release", "odd-even-minor", "next"),
            ("2147483648.1.0", "release", "odd-even-minor", "next"),
        ):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                version.calculate_version(*arguments)
        self.assertEqual(
            version.calculate_version(
                "2027.1.0", "release", "odd-even-minor", "previous"
            ),
            "2027.0.0",
        )

    def test_calculated_modes_cli_output_is_read_only(self):
        with tempfile.TemporaryDirectory(prefix="next version ") as directory:
            root = Path(directory)
            manifest = root / "package.json"
            original = json.dumps({"version": "2026.9.7-dev+build"})
            manifest.write_text(original, encoding="utf-8")
            output = root / "outputs"
            for mode, kind, suffix, expected in (
                ("previous", "release", "ignored+suffix", "2026.8.0"),
                ("next", "pre-release", "dev", "2026.11.0-dev"),
            ):
                with self.subTest(mode=mode):
                    output.write_text("", encoding="utf-8")
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(ACTION / "scripts" / "extension_version.py"),
                            f"--package-json-path={manifest}",
                            f"--type={kind}",
                            "--strategy=odd-even-minor",
                            f"--mode={mode}",
                            f"--pre-release-suffix={suffix}",
                        ],
                        cwd=root,
                        env={**os.environ, "GITHUB_OUTPUT": str(output)},
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    self.assertEqual(result.stdout.strip(), expected)
                    self.assertEqual(
                        output.read_text(encoding="utf-8").strip(),
                        f"version={expected}",
                    )
                    self.assertEqual(manifest.read_text(encoding="utf-8"), original)

    def test_cli_rejects_invalid_choices_or_missing_required_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "package.json"
            manifest.write_text('{"version":"1.45.0"}', encoding="utf-8")
            for arguments, error in (
                (
                    ["--mode=unknown", "--type=release", "--strategy=odd-even-minor"],
                    "invalid choice",
                ),
                *(
                    ([f"--mode={mode}", *options], error)
                    for mode in ("current", "next", "previous")
                    for options, error in (
                        ([], "the following arguments are required: --type, --strategy"),
                        (["--strategy=odd-even-minor"], "required: --type"),
                        (["--type=release"], "required: --strategy"),
                    )
                ),
                *(
                    (
                        [
                            f"--mode={mode}",
                            "--type=release",
                            "--strategy=odd-even-minor",
                            invalid_option,
                        ],
                        "invalid choice",
                    )
                    for mode in ("current", "next", "previous")
                    for invalid_option in (
                        "--type=invalid",
                        "--strategy=invalid",
                        "--type=",
                        "--strategy=",
                    )
                ),
            ):
                with self.subTest(arguments=arguments):
                    output = root / "outputs"
                    output.write_text("", encoding="utf-8")
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(ACTION / "scripts" / "extension_version.py"),
                            f"--package-json-path={manifest}",
                            *arguments,
                        ],
                        cwd=root,
                        env={**os.environ, "GITHUB_OUTPUT": str(output)},
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(error, result.stderr)
                    self.assertEqual(output.read_text(encoding="utf-8"), "")


if __name__ == "__main__":
    unittest.main()
