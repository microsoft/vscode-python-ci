#!/usr/bin/env bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

set -euo pipefail

: "${GITHUB_OUTPUT:?}" "${GITHUB_STEP_SUMMARY:?}"
: "${SUBMODULE_PATH:?}" "${PINNED_SHA:?}" "${LATEST_SHA:?}"

status=outdated
if [[ "$PINNED_SHA" == "$LATEST_SHA" ]]; then status=current; fi

printf 'status=%s\npinned-sha=%s\nlatest-sha=%s\n' \
    "$status" "$PINNED_SHA" "$LATEST_SHA" >> "$GITHUB_OUTPUT"

printf '### Submodule freshness\n\nPath: `%s`  \nBranch: `%s`  \nStatus: **%s**\n\nPinned: `%s`  \nLatest: `%s`\n' \
    "$SUBMODULE_PATH" "${SUBMODULE_BRANCH:-main}" "$status" "$PINNED_SHA" "$LATEST_SHA" \
    >> "$GITHUB_STEP_SUMMARY"
printf '%s: %s (pinned %s, latest %s)\n' "$SUBMODULE_PATH" "$status" "$PINNED_SHA" "$LATEST_SHA"
