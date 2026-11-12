#!/usr/bin/env bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

set -euo pipefail

fail() { printf '%s\n' "$1" >&2; exit 1; }

: "${SUBMODULE_COMMIT:?}" "${SUBMODULE_PATH:?}" "${GITHUB_OUTPUT:?}"
config_blob="${SUBMODULE_COMMIT}:.gitmodules"
key=$(git config --blob "$config_blob" --fixed-value --name-only \
    --get-regexp '^submodule\..*\.path$' "$SUBMODULE_PATH") \
    || fail "No matching submodule path in the committed .gitmodules."
[[ "$key" != *$'\n'* ]] \
    || fail "Expected exactly one matching submodule path in the committed .gitmodules."

url=$(git config --blob "$config_blob" --get-all "${key%.path}.url") \
    || fail "No upstream URL configured for the committed submodule."
[[ -n "$url" && "$url" != *$'\n'* && "$url" != *$'\r'* ]] \
    || fail "Expected exactly one upstream URL for the committed submodule."
case "$url" in
    /*|*:*) ;;
    *) fail "Use an absolute upstream URL or path in .gitmodules." ;;
esac

branch=${SUBMODULE_BRANCH:-main}
ref="refs/heads/$branch"
remote=$(git ls-remote --exit-code -- "$url" "$ref" 2>/dev/null) \
    || fail "Unable to query the configured upstream branch."
latest_sha=${remote%%$'\t'*}
[[ "$remote" == "$latest_sha"$'\t'"$ref" && "$latest_sha" =~ ^([[:xdigit:]]{40}|[[:xdigit:]]{64})$ ]] \
    || fail "Expected exactly one upstream branch tip for $branch."

printf 'sha=%s\n' "$latest_sha" >> "$GITHUB_OUTPUT"
