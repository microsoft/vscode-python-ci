# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "get-extension-version" / "scripts")
)
from extension_version import (
    MAX_MARKETPLACE_COMPONENT,
    output_version,
    parse_manifest,
    version_key,
)


def json_equal(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            json_equal(value, right[key]) for key, value in left.items()
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            json_equal(a, b) for a, b in zip(left, right)
        )
    return left == right


def validate_change(before_text, after_text):
    before, after = parse_manifest(before_text), parse_manifest(after_text)
    before_version, version = before.pop("version"), after.pop("version")
    if before_version == version:
        return None
    if not json_equal(before, after):
        raise ValueError("Only package.json's top-level version may change")
    key = version_key(version)
    if key <= version_key(before_version):
        raise ValueError("package.json's version must increase")
    major, minor, _ = key[0]
    if minor % 2 != 1:
        raise ValueError("The development minor must be positive and odd")
    if major > MAX_MARKETPLACE_COMPONENT or minor > MAX_MARKETPLACE_COMPONENT:
        raise ValueError("Release major and minor exceed Marketplace numeric bounds")
    return version


def serialize_release(text, version):
    exact = parse_manifest(text)
    document = parse_manifest(text, exact=False)
    exact["version"] = document["version"] = version
    result = json.dumps(document, indent=4, ensure_ascii=False, allow_nan=False) + "\n"
    if not json_equal(exact, parse_manifest(result)):
        raise ValueError("Serializing package.json would change other JSON values")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-version", help="Write the calculated stable version")
    args = parser.parse_args()
    try:
        directory = Path(os.environ["RUNNER_TEMP"])
        before = (directory / "release-pr.before.json").read_text(encoding="utf-8")
        after = (directory / "release-pr.after.json").read_text(encoding="utf-8")
        version = validate_change(before, after)
        if version is None:
            return 0
        source = after
        if args.release_version is not None:
            source = (directory / "release-pr.merged.json").read_text(encoding="utf-8")
            if parse_manifest(source)["version"] != version:
                raise ValueError(
                    "Merged package.json version does not match the release PR"
                )
            version = args.release_version
            version_key(version)
        text = serialize_release(source, version)
        if args.release_version is not None:
            Path("package.json").write_text(text, encoding="utf-8")
        output_version(version)
        return 0
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        message = str(exc).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::error::{message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
