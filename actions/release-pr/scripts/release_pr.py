# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
import os
import string
import sys
from decimal import Decimal
from pathlib import Path


def unique_object(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("Duplicate JSON keys are not allowed")
    return result


def invalid_constant(value):
    raise ValueError(f"Invalid JSON number: {value}")


def parse_manifest(text, exact=True):
    document = json.loads(
        text,
        object_pairs_hook=unique_object,
        parse_constant=invalid_constant,
        parse_int=Decimal if exact else int,
        parse_float=Decimal if exact else float,
    )
    if not isinstance(document, dict) or not isinstance(document.get("version"), str):
        raise TypeError("package.json must be an object with a string version")
    return document


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


def version_key(version):
    core_suffix, metadata_marker, metadata = version.partition("+")
    core, suffix_marker, suffix = core_suffix.partition("-")
    components = core.split(".")
    if len(components) != 3 or any(
        not part
        or not part.isascii()
        or not part.isdecimal()
        or (len(part) > 1 and part.startswith("0"))
        for part in components
    ):
        raise ValueError(f"Expected a three-component version: {version}")
    allowed = string.ascii_letters + string.digits + "-"
    for marker, identifiers, prerelease in (
        (suffix_marker, suffix, True),
        (metadata_marker, metadata, False),
    ):
        if marker and any(
            not part
            or any(c not in allowed for c in part)
            or (
                prerelease
                and part.isdecimal()
                and len(part) > 1
                and part.startswith("0")
            )
            for part in identifiers.split(".")
        ):
            raise ValueError(f"Invalid version suffix or metadata: {version}")
    suffix_key = (
        tuple(
            (0, int(part)) if part.isdecimal() else (1, part)
            for part in suffix.split(".")
        )
        if suffix_marker
        else ()
    )
    return tuple(map(int, components)), not suffix_marker, suffix_key


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
    if major > 2147483647 or minor > 2147483647:
        raise ValueError("Release major and minor exceed Marketplace numeric bounds")
    return version, f"{major}.{minor - 1}.0"


def serialize_release(text, version):
    exact = parse_manifest(text)
    document = parse_manifest(text, exact=False)
    exact["version"] = document["version"] = version
    result = json.dumps(document, indent=4, ensure_ascii=False, allow_nan=False) + "\n"
    if not json_equal(exact, parse_manifest(result)):
        raise ValueError("Serializing package.json would change other JSON values")
    return result


def main():
    try:
        mode = os.environ.get("RELEASE_MODE", "")
        if mode not in {"plan", "release"}:
            raise ValueError("mode must be plan or release")
        directory = Path(os.environ["RUNNER_TEMP"])
        before = (directory / "release-pr.before.json").read_text(encoding="utf-8")
        after = (directory / "release-pr.after.json").read_text(encoding="utf-8")
        versions = validate_change(before, after)
        if versions is None:
            return 0
        version, stable_version = versions
        if mode == "release":
            version = stable_version
            text = serialize_release(after, version)
            Path("package.json").write_text(text, encoding="utf-8")
        if os.environ.get("GITHUB_OUTPUT"):
            with Path(os.environ["GITHUB_OUTPUT"]).open(
                "a", encoding="utf-8"
            ) as destination:
                destination.write(f"version={version}\n")
        print(version)
        return 0
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        message = str(exc).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::error::{message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
