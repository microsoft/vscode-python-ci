#!/usr/bin/env bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

set -euo pipefail

commit=$(git rev-parse --verify HEAD)
entry=$(git --literal-pathspecs ls-tree "$commit" -- "${SUBMODULE_PATH:?}")
read -r mode type pinned_sha _ <<< "$entry"
if [[ "$mode" != 160000 || "$type" != commit ]]; then
    printf 'Not a committed submodule: %s\n' "$SUBMODULE_PATH" >&2
    exit 1
fi

paths=$(git config --blob "$commit:.gitmodules" --get-regexp '^submodule\..*\.path$')
module_key=
while IFS= read -r entry; do
    if [[ "$entry" == *" $SUBMODULE_PATH" ]]; then
        key=${entry%" $SUBMODULE_PATH"}
        if [[ "$key" == submodule.*.path ]]; then
            module_key=${key%.path}
            break
        fi
    fi
done <<< "$paths"
if [[ -z "$module_key" ]]; then
    printf 'Submodule path is not configured in committed .gitmodules: %s\n' "$SUBMODULE_PATH" >&2
    exit 1
fi
url=$(git config --blob "$commit:.gitmodules" --get "$module_key.url")
case "$url" in
    /* | *://* | *:*) ;;
    *)
        printf 'Use an absolute upstream URL or path in .gitmodules.\n' >&2
        exit 1
        ;;
esac

branch=${SUBMODULE_BRANCH:-main}
remote=$(GIT_TERMINAL_PROMPT=0 git ls-remote --exit-code -- "$url" "refs/heads/$branch")
read -r latest_sha ref <<< "$remote"
if [[ -z "$latest_sha" || "$ref" != "refs/heads/$branch" || "$remote" == *$'\n'* ]]; then
    printf 'Expected exactly one upstream branch tip for %s.\n' "$branch" >&2
    exit 1
fi

status=outdated
if [[ "$pinned_sha" == "$latest_sha" ]]; then
    status=current
fi

printf 'status=%s\npinned-sha=%s\nlatest-sha=%s\n' \
    "$status" "$pinned_sha" "$latest_sha" >> "$GITHUB_OUTPUT"
printf '### Submodule freshness\n\nPath: `%s`  \nBranch: `%s`  \nStatus: **%s**\n\nPinned: `%s`  \nLatest: `%s`\n' \
    "$SUBMODULE_PATH" "$branch" "$status" "$pinned_sha" "$latest_sha" >> "$GITHUB_STEP_SUMMARY"
printf '%s: %s (pinned %s, latest %s)\n' "$SUBMODULE_PATH" "$status" "$pinned_sha" "$latest_sha"

if [[ "$status" == outdated && "${FAIL_IF_OUTDATED:-true}" != false ]]; then
    exit 1
fi
