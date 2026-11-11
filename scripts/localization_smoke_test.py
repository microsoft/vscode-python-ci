# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Opt-in round trips through the pinned CLI without credentials or live drops."""

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

import localization


@unittest.skipUnless(
    os.environ.get("LOCALIZATION_CLI_SMOKE") == "1",
    "Set LOCALIZATION_CLI_SMOKE=1 to run the real pinned localization CLI.",
)
class LocalizationSmokeTests(unittest.TestCase):
    """Cover manifest-only, standalone-runtime, and shared-source consumers."""

    def test_export_import_round_trips(self):
        for profile in ("manifest", "runtime", "shared"):
            with self.subTest(profile=profile):
                with tempfile.TemporaryDirectory(prefix="localization CLI ") as folder:
                    self.round_trip(pathlib.Path(folder).resolve(), profile)

    def round_trip(self, base, profile):
        root = base / "extension source"
        root.mkdir()
        package = {"publisher": "fixture", "name": profile}
        runtime = profile != "manifest"
        if runtime:
            package["l10n"] = "./l10n"
        (root / "package.json").write_text(json.dumps(package), encoding="utf-8")
        english = (
            b'{"description":{"message":"English description",'
            b'"comment":["Keep command links unchanged"]},"fallback":"Keep English"}\n'
        )
        (root / "package.nls.json").write_bytes(english)
        source = root / "src"
        source.mkdir()
        (source / "extension.ts").write_text(
            'import * as vscode from "vscode";\nvscode.l10n.t("Open logs");\n',
            encoding="utf-8",
        )
        sources = ["src"]
        runtime_strings = {"Open logs": "Open logs"}
        if profile == "shared":
            shared = root / "external" / "vscode-common-python-lsp" / "typescript" / "src"
            shared.mkdir(parents=True)
            (shared / "shared.ts").write_text(
                'import * as vscode from "vscode";\nvscode.l10n.t("Shared message");\n',
                encoding="utf-8",
            )
            sources.append("external/vscode-common-python-lsp/typescript/src")
            runtime_strings["Shared message"] = "Shared message"
        output = base / "english staging"
        self.run_helper(
            root, output, "--operation", "export", "--source-paths", json.dumps(sources)
        )
        extension_id = f"fixture.{profile}"
        xlf = output / f"{extension_id}-new.xlf"
        self.assertNotIn(b"\r", xlf.read_bytes())
        document = ET.parse(xlf)
        tables = {table.get("original") for table in document.findall(".//{*}file")}
        self.assertEqual(tables, {"package", "bundle"} if runtime else {"package"})
        self.assertIn(
            "Keep command links unchanged",
            [note.text for note in document.findall(".//{*}note")],
        )
        if runtime:
            self.assertEqual(
                localization.read_table(output / "bundle.l10n.json"), runtime_strings
            )
        else:
            self.assertFalse((output / "bundle.l10n.json").exists())
        translations = base / "translated handbacks"
        ET.register_namespace("", "urn:oasis:names:tc:xliff:document:1.2")
        for locale in localization.LOCALES:
            translated = ET.parse(xlf)
            for table in translated.findall(".//{*}file"):
                table.set(
                    "target-language",
                    {"zh-cn": "zh-Hans", "zh-tw": "zh-Hant"}.get(locale, locale),
                )
                for unit in table.findall(".//{*}trans-unit"):
                    source_text = unit.find("{*}source")
                    if source_text.text == "Keep English" or locale == "fr":
                        continue
                    namespace = source_text.tag.removesuffix("source")
                    target = ET.SubElement(unit, f"{namespace}target", {"state": "new"})
                    target.text = (
                        source_text.text
                        if locale == "de"
                        else f"{locale}: {source_text.text}"
                    )
            directory = translations / extension_id / locale
            directory.mkdir(parents=True)
            translated.write(
                directory / xlf.name, encoding="utf-8", xml_declaration=True
            )
        self.run_helper(
            root,
            base / "import staging",
            "--operation",
            "import",
            "--translations-root",
            str(translations.relative_to(base)),
        )
        self.assertEqual((root / "package.nls.json").read_bytes(), english)
        self.assertEqual(len(list(root.glob("package.nls.*.json"))), 14)
        for locale in localization.LOCALES:
            prefix = "" if locale == "de" else f"{locale}: "
            self.assertEqual(
                json.loads(
                    (root / f"package.nls.{locale}.json").read_text(encoding="utf-8-sig")
                ),
                {} if locale == "fr" else {"description": f"{prefix}English description"},
            )
            if runtime:
                self.assertEqual(
                    json.loads(
                        (root / "l10n" / f"bundle.l10n.{locale}.json").read_text(
                            encoding="utf-8-sig"
                        )
                    ),
                    {}
                    if locale == "fr"
                    else {
                        key: f"{prefix}{value}" for key, value in runtime_strings.items()
                    },
                )
        if not runtime:
            self.assertFalse((root / "l10n").exists())

    def run_helper(self, root, output, *arguments):
        helper = pathlib.Path(__file__).with_name("localization.py")
        subprocess.run(
            [
                sys.executable,
                str(helper),
                "--extension-root",
                str(root),
                "--output-directory",
                str(output),
                *arguments,
            ],
            cwd=root.parent,
            check=True,
        )


if __name__ == "__main__":
    unittest.main()
