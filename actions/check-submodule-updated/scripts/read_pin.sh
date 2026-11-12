#!/usr/bin/env bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

set -euo pipefail

path=${SUBMODULE_PATH-}
[[ -n "$path" && "$path" != */ ]] || {
    echo "Use the exact submodule path, without a trailing slash." >&2
    exit 1
}

: "${GITHUB_OUTPUT:?}"

commit=$(git rev-parse --verify HEAD)
entry=$(git --literal-pathspecs ls-tree \
    --format='%(objectmode) %(objecttype) %(objectname)' \
    "$commit" -- "$path")
[[ "$entry" =~ ^160000[[:space:]]commit[[:space:]]([[:xdigit:]]+)$ ]] || {
    echo "Not a committed submodule: $path" >&2
    exit 1
}

printf 'commit=%s\npinned-sha=%s\n' "$commit" "${BASH_REMATCH[1]}" >> "$GITHUB_OUTPUT"
