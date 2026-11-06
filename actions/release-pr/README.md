# Prepare extension releases

One composite action, two modes, one manifest (`package.json`), and one output
(`version`). Git operations and the sole-file gate are short YAML steps.
Python runs once to compare the exported JSON snapshots, validate versions, and
optionally write the stable manifest. It has no runtime
dependencies outside Python's standard library and never invokes Git or GitHub
APIs.

## Behavior

**Plan:** check out the PR head and run `git diff` against the recorded base.
Only when `package.json` is the sole changed file, export the merge-base/head
manifests with `git show` and compare them with Python. The file mode must stay
the same, and only the top-level version may change. Formatting/key order are
ignored, but nested values and array order must remain unchanged.

The new version must be a strictly greater SemVer with a positive odd minor.
Build metadata alone is not an upgrade. There is no old-minor-plus-two rule or
automatic calendar rollover.

Other diffs, and single-manifest PRs with no version change, succeed with no
output. A version bump mixed with other files is intentionally not classified
as a release.
Additions, deletions, symlinks, and file-mode changes to a sole changed
`package.json` fail. Renames involve another path and skip comparison.

**Release:** check out the exact merged commit and reuse the same validation
against the event's recorded target base. This compares the entire merged
change, not just its final commit, including multi-commit rebases. Then update
the parsed manifest, stage it, commit, and push the finished commit directly to
`release/<stable-version>`.

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
even on retries**; there is no branch reconciliation or overwrite. The target
branch is never pushed. No checked-out PR scripts are executed, and commit hooks
are disabled. This action uses event snapshots, not live API state or plan artifacts.

## Inputs and output

| Input   | Default               | Meaning                                                                      |
| ------- | --------------------- | ---------------------------------------------------------------------------- |
| `mode`  | Required              | `plan` for an open `pull_request`; `release` for a merged `closed` PR event. |
| `token` | `${{ github.token }}` | `contents: read` for plan; `contents: write` for release.                    |

**`version`** is the validated development version in plan mode, the stable
version in release mode, and empty for an ordinary PR. Failures return a nonzero
exit code and no successful action result.

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

Use the same reviewed action SHA in both jobs. The action performs checkout
itself; use a dedicated job, since it changes the workspace and release mode
creates a local commit.

Configure **Release PR / Plan** as a required check on the current revision in
branch protection/rulesets. The action cannot enforce that setting itself.
The bot must be allowed to create `release/*` refs.

The closed `pull_request_target` event uses the trusted target-branch workflow
and supports merged fork PRs with a write token. Do not add steps that execute
checked-out PR code. An internal `pull_request` closed-event caller also works
with a write token.

Existing Azure pipelines must already trigger on `release/*` and enable
publishing in the merged source. GitHub's token normally suppresses subsequent
GitHub Actions push workflows; Azure is a separate integration. Existing
approvals and build-number stamping are unchanged. No Azure publishing is
performed by the local tests.

## Tests

```sh
python -m unittest discover -s actions/release-pr/tests -v
```

Focused tests cover version-only JSON changes, upgrade rules, ordinary PRs, and
lossless release serialization. A small local Git fixture executes the actual
YAML commands for plan/release behavior, whole-change gating after a rebase,
file-mode rejection, and creation-only pushes. CI runs them on Linux, Windows,
and macOS and invokes the real read-only action on this repository's PR.
