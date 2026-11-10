# Prepare extension releases

One composite action, two modes, one manifest (`package.json`), and two outputs
(`version` and `branch`). Git operations and the sole-file gate are short YAML steps.
The author-permission lookup is also a short YAML step.
Python compares the exported JSON snapshots and validates versions, then uses
[get-extension-version](../get-extension-version/README.md) to derive the
previous stable version from the validated source snapshot. In release mode,
Python revalidates the snapshots and writes the calculated stable manifest.
All Python code uses only the standard library and never invokes Git or GitHub
APIs. The GitHub CLI performs the permission lookup.

## Behavior

**Plan:** check out the PR head and run `git diff` against the recorded base.
Only when `package.json` is the sole changed file, export the merge-base/head
manifests with `git show` and compare them with Python. The file mode must stay
the same, and only the top-level version may change. Formatting/key order are
ignored, but nested values and array order must remain unchanged.

The new version must be a strictly greater SemVer with a positive odd minor.
Build metadata alone is not an upgrade. There is no old-minor-plus-two rule or
automatic calendar rollover.

Release candidates must also be opened by a GitHub user with **write, maintain,
or admin** access to the target repository. The action checks the PR creator
(`pull_request.user.login`), not spoofable Git author names/emails, the workflow
actor, or the person merging the PR. It uses GitHub's
[repository-permission endpoint](https://docs.github.com/en/rest/collaborators/collaborators#get-repository-permissions-for-a-user);
custom roles are evaluated through their base permission.

Both modes check current permissions before preparing a stable manifest or
creating a commit. Read/triage/no access, missing or unexpected permission
values, and API/authentication failures reject the release candidate. Membership
in a particular team is not required, and no bot exception is provided.
Repository write access is the merge-capable role threshold, not an exemption
from branch protections, required reviews, or other merge requirements.

The calculator is called only after release classification, with `type: release`,
`strategy: odd-even-minor`, and `mode: previous`. Its prerelease calculation
does not constrain the submitted development bump: larger valid jumps remain
accepted. Both plan and release use the same calculation, but plan still returns
the submitted development version.
Plan also checks that the manifest can be serialized losslessly, without
writing it, so serialization failures are caught before merge.

Other diffs, and single-manifest PRs with no version change, succeed with no
output. A version bump mixed with other files is intentionally not classified
as a release. These ordinary PRs do not perform an author-permission lookup.
Additions, deletions, symlinks, and file-mode changes to a sole changed
`package.json` fail. Renames involve another path and skip comparison.

**Release:** check out the exact merged commit, but classify and validate the
entire original PR diff using the event's recorded base and PR head. This
includes all PR commits, including multi-commit rebases, without treating
unrelated target-branch updates as part of the PR. Both commits are fetched
explicitly, so the source branch need not still exist.

The merged manifest must be a regular file and its development version must
match the validated PR version. Then update the parsed **merged** manifest,
preserving other values integrated from the target branch, stage it, commit,
and push the finished commit directly to
`<release-branch-prefix><stable-version>` (by default, `release/<stable-version>`).

Stable versions preserve major, subtract one from minor, set patch to zero, and
remove prerelease/build metadata:

```text
2026.9.0-dev -> 2026.8.0
2026.13.0   -> 2026.12.0
1.45.0      -> 1.44.0
2027.1.0    -> 2027.0.0
```

Serialization uses four-space indentation and a final newline, checking that
other JSON values are preserved. Release major/minor must fit Marketplace's
`0..2147483647` bounds.

The push uses an empty lease, allowing creation only. **Existing branches fail,
even on retries**; there is no branch reconciliation or overwrite. Up-to-date
pushes are also rejected when the release ref already equals the prepared commit.
The PR's target
branch is never pushed. No checked-out PR scripts are executed, and commit hooks
are disabled. Manifest validation uses event snapshots, not plan artifacts;
author permissions are queried live and rechecked at release time.

## Inputs and outputs

| Input                   | Default               | Meaning                                                                                                              |
| ----------------------- | --------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `mode`                  | Required              | `plan` for an open `pull_request`; `release` for a merged `closed` PR event.                                         |
| `release-branch-prefix` | `release/`            | Prefix prepended to the calculated stable version, for example `release/` or `stable/v`.                             |
| `token`                 | `${{ github.token }}` | `contents: read` for plan; `contents: write` for release; repository metadata read access for the permission lookup. |

**`version`** is the validated development version in plan mode, the stable
version in release mode, and empty for an ordinary PR. Failures return a nonzero
exit code and no successful action result.

**`branch`** is the full release branch name in both modes, for example
`release/2026.8.0`, and empty for an ordinary PR. Plan reports the branch without
creating it. An explicit empty prefix produces just the stable version.

For release candidates, both modes validate the resulting
`refs/heads/<prefix><stable-version>` with `git check-ref-format` before modifying
the manifest or creating a commit. Invalid names fail; ordinary PRs still skip.
The prefix is literal, not a wildcard or template, and version calculation
cannot be overridden.

All eight Python extensions use their root manifest.
**Python Environments' `api/package.json` is outside this action** and retains
its independent npm publishing flow. A release PR cannot also modify it.

## Consumer workflow

```yaml
name: Release PR

on:
  pull_request:
    branches: [main]
    types: [opened, reopened, synchronize, edited]
  pull_request_target:
    branches: [main]
    types: [closed]

permissions:
  contents: read

jobs:
  plan:
    name: Release PR / Plan
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    steps:
      - uses: microsoft/vscode-python-ci/actions/release-pr@<reviewed-commit-sha>
        with:
          mode: plan

  release:
    name: Release PR / Release
    if: github.event_name == 'pull_request_target' && github.event.pull_request.merged == true
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: microsoft/vscode-python-ci/actions/release-pr@<reviewed-commit-sha>
        with:
          mode: release
```

Use the same reviewed action SHA and `release-branch-prefix` in both jobs.
Omit the prefix to keep the default `release/<stable-version>` naming, or set
`release-branch-prefix: stable/v` to produce, for example, `stable/v2026.8.0`.
The action performs checkout
itself; use a dedicated job, since it changes the workspace and release mode
creates a local commit.

GitHub CLI (`gh`) must be available; GitHub-hosted runners include it.
The default `github.token` provides repository metadata read access. Custom
GitHub App/fine-grained tokens must also have **Metadata: read**.
No organization-membership permission is needed.

Nested actions use `$/` sibling references at the same repository/ref as the
pinned release action. GitHub.com and runner **2.336.0 or newer** are required;
GitHub Enterprise Server is not supported.

Configure **Release PR / Plan** as a required check on the current revision in
branch protection/rulesets. The action cannot enforce that setting itself.
The bot must be allowed to create refs matching the configured prefix
(`release/*` by default).

The closed `pull_request_target` event uses the trusted target-branch workflow
and supports merged fork PRs with a write token. Do not add steps that execute
checked-out PR code. An internal `pull_request` closed-event caller also works
with a write token.

Existing Azure pipelines must already trigger on the configured branch pattern
(`release/*` by default) and enable
publishing in the merged source. GitHub's token normally suppresses subsequent
GitHub Actions push workflows; Azure is a separate integration. Existing
approvals and build-number stamping are unchanged. No Azure publishing is
performed by the local tests.

## Tests

```sh
python -m unittest discover -s actions/release-pr/tests -v
python -m unittest discover -s actions/get-extension-version/tests -v
```

Focused tests cover version-only JSON changes, upgrade rules, ordinary PRs, and
lossless release serialization. A small local Git fixture executes the actual
YAML commands for plan/release behavior, stale-base squash/merge/rebase handling,
preservation of merged manifest values, merged-version mismatch rejection,
whole-PR gating after a rebase,
file-mode rejection, configurable branch names, invalid-prefix rejection before
writes, author permissions and fail-closed lookup failures, authorization skips
for ordinary PRs, creation-only pushes, and the version-action command. Local
permission lookups are mocked.
The version-action suite covers its standalone contract. CI runs both suites
on Linux, Windows, and macOS, invokes the real read-only release action on this
repository's PR, verifies the permission endpoint with `github.token`, and
smoke-tests all version modes with no repository checkout.
