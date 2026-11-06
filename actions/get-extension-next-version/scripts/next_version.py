# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import os
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "get-extension-version" / "scripts")
)
from extension_version import MAX_MARKETPLACE_COMPONENT, output_version, version_key


def next_version(
    version, version_type, strategy, direction="next", pre_release_suffix=""
):
    if version_type not in {"pre-release", "release"}:
        raise ValueError("type must be pre-release or release")
    if strategy != "odd-even-minor":
        raise ValueError("strategy must be odd-even-minor")
    if direction not in {"next", "previous"}:
        raise ValueError("direction must be next or previous")
    (major, minor, _), _, _ = version_key(version)
    target_parity = 1 if version_type == "pre-release" else 0
    step = 1 if direction == "next" else -1
    minor += step
    if minor % 2 != target_parity:
        minor += step
    if not (
        0 <= major <= MAX_MARKETPLACE_COMPONENT
        and 0 <= minor <= MAX_MARKETPLACE_COMPONENT
    ):
        raise ValueError(
            f"Result exceeds Marketplace numeric bounds (0..{MAX_MARKETPLACE_COMPONENT})"
        )
    result = f"{major}.{minor}.0"
    if version_type == "pre-release" and pre_release_suffix:
        if pre_release_suffix.startswith("-") or "+" in pre_release_suffix:
            raise ValueError(
                "pre-release-suffix must omit the leading - and build metadata"
            )
        result += f"-{pre_release_suffix}"
    version_key(result)
    return result


if __name__ == "__main__":
    output_version(
        next_version(
            os.environ["CURRENT_VERSION"],
            os.environ["VERSION_TYPE"],
            os.environ["VERSION_STRATEGY"],
            os.environ.get("VERSION_DIRECTION", "next"),
            os.environ.get("PRE_RELEASE_SUFFIX", ""),
        )
    )
