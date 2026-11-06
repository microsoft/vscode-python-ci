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
GETTER = ACTION.parent / "get-extension-version"
SPEC = importlib.util.spec_from_file_location(
    "next_version", ACTION / "scripts" / "next_version.py"
)
calculator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(calculator)
from extension_version import read_version


class VersionActionsTests(unittest.TestCase):
    def test_getter_default_and_custom_paths_are_read_only(self):
        with tempfile.TemporaryDirectory(prefix="version actions ") as directory:
            root = Path(directory)
            for name in ("package.json", str(Path("nested space") / "custom.json")):
                with self.subTest(path=name):
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    original = (
                        b'{"version":"1.45.7-rc.1+build.2","nested":{"version":"keep"}}'
                    )
                    path.write_bytes(original)
                    output = root / "outputs"
                    environment = {**os.environ, "GITHUB_OUTPUT": str(output)}
                    environment.pop("PACKAGE_JSON_PATH", None)
                    if name != "package.json":
                        environment["PACKAGE_JSON_PATH"] = name
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(GETTER / "scripts" / "extension_version.py"),
                        ],
                        cwd=root,
                        env=environment,
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
                read_version(path)
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
                        read_version(path)

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
                    calculator.next_version(
                        f"2026.{minor}.7-dev+build", kind, "odd-even-minor", direction
                    ),
                    f"2026.{expected}.0",
                )

    def test_suffix_handling(self):
        for suffix in ("", "dev", "rc.1"):
            with self.subTest(suffix=suffix):
                self.assertEqual(
                    calculator.next_version(
                        "1.45.0",
                        "pre-release",
                        "odd-even-minor",
                        pre_release_suffix=suffix,
                    ),
                    "1.47.0" + (f"-{suffix}" if suffix else ""),
                )
        self.assertEqual(
            calculator.next_version(
                "1.45.0-dev", "release", "odd-even-minor", "previous", "ignored+suffix"
            ),
            "1.44.0",
        )
        for suffix in ("-dev", "dev+build", "00", "rc..1", "dev\nextra=output"):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                calculator.next_version(
                    "1.45.0", "pre-release", "odd-even-minor", pre_release_suffix=suffix
                )

    def test_invalid_options_and_numeric_boundaries(self):
        for arguments in (
            ("1.45.0", "stable", "odd-even-minor"),
            ("1.45.0", "release", "calendar"),
            ("1.45.0", "release", "odd-even-minor", "back"),
            ("1.0.0", "release", "odd-even-minor", "previous"),
            ("1.0.0", "pre-release", "odd-even-minor", "previous"),
            ("1.1.0", "pre-release", "odd-even-minor", "previous"),
            ("1.2147483647.0", "release", "odd-even-minor"),
            ("1.2147483647.0", "pre-release", "odd-even-minor"),
            ("2147483648.1.0", "release", "odd-even-minor"),
        ):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                calculator.next_version(*arguments)
        self.assertEqual(
            calculator.next_version(
                "2027.1.0", "release", "odd-even-minor", "previous"
            ),
            "2027.0.0",
        )

    def test_calculator_cli_output_is_read_only(self):
        with tempfile.TemporaryDirectory(prefix="next version ") as directory:
            root = Path(directory)
            manifest = root / "package.json"
            original = json.dumps({"version": "2026.9.7-dev+build"})
            manifest.write_text(original, encoding="utf-8")
            output = root / "outputs"
            result = subprocess.run(
                [sys.executable, str(ACTION / "scripts" / "next_version.py")],
                cwd=root,
                env={
                    **os.environ,
                    "CURRENT_VERSION": read_version(manifest),
                    "VERSION_TYPE": "release",
                    "VERSION_STRATEGY": "odd-even-minor",
                    "VERSION_DIRECTION": "previous",
                    "PRE_RELEASE_SUFFIX": "ignored",
                    "GITHUB_OUTPUT": str(output),
                },
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(result.stdout.strip(), "2026.8.0")
            self.assertEqual(
                output.read_text(encoding="utf-8").strip(), "version=2026.8.0"
            )
            self.assertEqual(manifest.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
