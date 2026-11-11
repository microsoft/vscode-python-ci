#!/usr/bin/env bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

set -euo pipefail

script="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/check-submodule-updated.sh"
temporary=$(mktemp -d)
trap 'rm -rf -- "$temporary"' EXIT

init_repo() {
    git init --quiet --initial-branch=main "$1"
    git -C "$1" config user.name Fixture
    git -C "$1" config user.email fixture@example.invalid
    git -C "$1" config commit.gpgsign false
}

upstream="$temporary/upstream library"
init_repo "$upstream"
git -C "$upstream" commit --quiet --allow-empty -m Initial
old_sha=$(git -C "$upstream" rev-parse HEAD)
git -C "$upstream" commit --quiet --allow-empty -m Latest
latest_sha=$(git -C "$upstream" rev-parse HEAD)
upstream=$(git -C "$upstream" rev-parse --show-toplevel)

consumer="$temporary/consumer repository"
init_repo "$consumer"
path="external/shared library"
git -C "$consumer" config -f .gitmodules 'submodule.Different module name.path' "$path"
git -C "$consumer" config -f .gitmodules 'submodule.Different module name.url' "$upstream"
git -C "$consumer" add .gitmodules
git -C "$consumer" update-index --add --cacheinfo "160000,$old_sha,$path"
git -C "$consumer" commit --quiet -m "Pin shared library"

branch=main
enforce=false
expected_pin=$old_sha
expected_latest=$latest_sha
passed=0

snapshot() {
    git -C "$consumer" rev-parse HEAD
    git -C "$consumer" ls-files --stage
    git -C "$consumer" status --porcelain
    git -C "$consumer" diff --binary HEAD
    git -C "$consumer" config --local --list
    if [[ -d "$consumer/external/shared library" ]]; then
        git -C "$consumer/external/shared library" rev-parse HEAD
        git -C "$consumer/external/shared library" config --local --list
    fi
}

check() {
    local name=$1 expected_exit=$2 expected_status=$3 before after result
    : > "$temporary/output"
    : > "$temporary/summary"
    before=$(snapshot)
    if (
        cd "$consumer"
        SUBMODULE_PATH="$path" SUBMODULE_BRANCH="$branch" FAIL_IF_OUTDATED="$enforce" \
            GITHUB_OUTPUT="$temporary/output" GITHUB_STEP_SUMMARY="$temporary/summary" \
            bash "$script"
    ) > "$temporary/log" 2>&1; then
        result=0
    else
        result=$?
    fi
    if [[ "$expected_exit" == failure ]]; then
        test "$result" -ne 0 || { cat "$temporary/log"; exit 1; }
        test ! -s "$temporary/output"
        test ! -s "$temporary/summary"
    else
        if [[ "$result" != "$expected_exit" ]]; then
            printf 'FAIL: %s (exit %s, expected %s)\n' "$name" "$result" "$expected_exit" >&2
            cat "$temporary/log"
            exit 1
        fi
        grep -Fx "status=$expected_status" "$temporary/output"
        grep -Fx "pinned-sha=$expected_pin" "$temporary/output"
        grep -Fx "latest-sha=$expected_latest" "$temporary/output"
        grep -F "Status: **$expected_status**" "$temporary/summary"
    fi
    after=$(snapshot)
    test "$before" = "$after"
    passed=$((passed + 1))
    printf 'PASS: %s\n' "$name"
}

test ! -d "$consumer/$path"
check "uninitialized, outdated, report-only, paths and module names with spaces" 0 outdated
enforce=true
check "outdated, enforcing, outputs available before failure" 1 outdated
enforce=
check "outdated, enforcement defaults to true" 1 outdated

git -C "$consumer" update-index --cacheinfo "160000,$latest_sha,$path"
git -C "$consumer" commit --quiet -m "Update shared library"
expected_pin=$latest_sha
check "current, enforcing" 0 current

git -C "$upstream" branch release "$old_sha"
branch=release
expected_latest=$old_sha
enforce=false
check "explicit upstream branch overrides main" 0 outdated
branch=main
expected_latest=$latest_sha

git -C "$consumer" -c protocol.file.allow=always submodule update --init -- "$path"
git -C "$consumer/$path" checkout --quiet --detach "$old_sha"
git -C "$consumer" config -f .gitmodules 'submodule.Different module name.url' "$temporary/missing remote"
git -C "$consumer" add .gitmodules "$path"
check "committed pin and config override staged and checked-out submodule state" 0 current

path=missing
check "missing path fails in report-only mode" failure ""
path=.gitmodules
check "regular file is not a submodule" failure ""
path="external/shared library"
branch=missing-branch
check "missing upstream branch fails in report-only mode" failure ""
branch=main

git -C "$consumer" commit --quiet -m "Use inaccessible upstream"
check "unavailable upstream fails in report-only mode" failure ""

git -C "$consumer" config -f .gitmodules 'submodule.Different module name.url' ../relative-upstream
git -C "$consumer" add .gitmodules
git -C "$consumer" commit --quiet -m "Use relative upstream"
check "unsupported relative upstream fails rather than checking the wrong repository" failure ""

printf '\n%s checks passed.\n' "$passed"
