# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
import os
import string
from decimal import Decimal
from pathlib import Path

MAX_MARKETPLACE_COMPONENT = 2_147_483_647


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


def version_key(version):
    """Return (core, is_stable, prerelease_key) for SemVer precedence.

    Build metadata is ignored; numeric prerelease identifiers sort before strings.
    """
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


def read_version(path):
    version = parse_manifest(Path(path).read_text(encoding="utf-8"))["version"]
    version_key(version)
    return version


def output_version(version):
    if os.environ.get("GITHUB_OUTPUT"):
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
            output.write(f"version={version}\n")
    print(version)


if __name__ == "__main__":
    output_version(read_version(os.environ.get("PACKAGE_JSON_PATH", "package.json")))
