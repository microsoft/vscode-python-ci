# Check CI Python versions

A Python-backed composite GitHub Action that checks declared Python matrices
against the newest Python 3 series with a published release candidate. It can
open a maintenance issue in the calling repository; it never edits workflows,
runs extension tests, or changes minimum-supported-version/build-runtime pins.

## Usage

Use a dedicated Ubuntu job. The caller owns the schedule, checkout, permissions,
and concurrency. Replace `<reviewed-commit-sha>` with a reviewed revision of this
repository before enabling the workflow.

```yaml
name: Check supported Python versions

on:
  schedule:
    - cron: '0 12 * * 1'
  workflow_dispatch:

permissions:
  contents: read
  issues: write

concurrency:
  group: check-supported-python-versions
  cancel-in-progress: false

jobs:
  check:
    if: github.repository_owner == 'microsoft'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - uses: microsoft/pylance-engineering/actions/check-python-versions@<reviewed-commit-sha>
        with:
          files: |
            - path: .github/workflows/pr-check.yml
              key: python
            - path: .github/workflows/push-check.yml
              key: python
          token: ${{ github.token }}
          issue-labels: debt,python-version
```

The weekly cron runs Mondays at 12:00 UTC. For `vscode-python`, supply
`.github/workflows/build.yml` instead of `push-check.yml`. Repository action
policies must allow this shared action and its pinned `actions/setup-python`.
For `vscode-python-environments`, use `key: python-version`. Keys are literal
matrix field names, not dotted paths. You can list the same file with different
keys when it contains multiple Python matrix fields.

## Inputs and outputs

| Input | Default | Description |
|---|---|---|
| `files` | Required | YAML list of `{path, key}` entries. Paths are checkout-relative; each key names the matrix field containing Python versions. Identical resolved path/key pairs are deduplicated. Globs are not supported. |
| `create-issue` | `true` | Exactly `true` or `false`. Missing coverage does not fail either mode. |
| `token` | Empty | Required in issue mode, even when coverage is already present. Use a token with issue write access to the caller repository. |
| `issue-labels` | Empty | Comma-separated labels that already exist in the caller repository. |

| Output | Description |
|---|---|
| `latest-version` | Selected release-candidate series, for example `3.15`. |
| `missing-matrices` | Compact JSON array such as `[{"file":".github/workflows/pr-check.yml","job":"test","key":"python"}]`; `[]` when covered. |
| `issue-url` | Newly created issue URL. Empty when covered or in check-only mode. |

Results also appear in the job summary. For check-only mode set
`create-issue: 'false'`, omit `token`, and grant only `contents: read`.

## Checking contract

The action reads files from `GITHUB_WORKSPACE` and its own code/dependencies from
`github.action_path`. Files must resolve inside the checkout, including symlink
targets. Absolute paths, missing files, and directories are rejected.

Each entry inspects only `jobs.<job>.strategy.matrix.<key>` in its specified file.
Other matrix fields are ignored; there are no hard-coded Python field names.
Supported matrices are nonempty static lists, inline or multiline. YAML scalars
are read as strings, so an unquoted `3.10` is not rounded to `3.1`.

Every explicit Python matrix must declare the selected major/minor series.
Patch, alpha/beta/RC, and dev suffixes normalize to that series, including
`3.15.0rc1`, `3.15.0.dev1`, and `3.15-dev`. Floating `3.x` values do not count as
explicit coverage. Floating-only matrices and unrelated jobs are ignored;
each supplied path/key pair must still have at least one explicit Python matrix.

Expressions in Python lists, fully dynamic matrices, Python `include`-only
matrices, and `include`/`exclude` on relevant Python matrices are unsupported
and fail clearly. Unrelated static `include` jobs are ignored. This is a
declaration check, not a general GitHub Actions matrix evaluator: it does not
evaluate job conditions, installation settings, or test results.

Python.org must return a JSON array of releases. Only published Python 3
release candidates dated at or before the current UTC time are eligible.
Alpha/beta releases do not trigger a new series. Malformed eligible RC dates,
an unexpected API response, or no eligible release candidates fail the check.

## Issues and execution

When coverage is missing, issue mode makes a single `gh issue create` call with
the title `CI Python Versions: Update to Python X.Y`.

**Duplicate detection is deferred to a future PR.** Every issue-mode run with
missing coverage creates a new issue, even if an issue for that series already
exists. Use check-only mode during rollout if repeated issue creation is unwanted.

The issue lists missing file/job/key matrices and asks maintainers to add coverage
and run tests without changing support-policy pins. Invalid labels, permissions,
and failed creation fail the job rather than silently succeeding. Caller
concurrency prevents overlapping runs but does not prevent duplicates across runs.

Ubuntu runners must have `gh` on PATH in issue mode (GitHub-hosted Ubuntu runners
do). The composite sets up Python 3.13 for tooling and installs pinned PyYAML
into that interpreter, then calls the checker script directly. It does not create
a virtual environment. Use a dedicated job because `setup-python` changes PATH
and dependency installation can affect subsequent Python steps.
Network access to Python.org and the configured package index is required; issue
mode also needs GitHub access.

## Validation

From the repository root:

```sh
python -m pip install -r actions/check-python-versions/requirements.txt
python -m unittest discover -s actions/check-python-versions/tests -v
```

Tests mock network/issue operations and cover release filtering, matrix parsing,
path validation, output generation, and failure handling. The repository's
`smoke-python-versions-action.yml` workflow runs the composite action in
check-only mode against a representative workflow fixture, then runs the unit
tests using the Python environment installed by the action. The smoke test
passes when the action exits successfully, without additional output assertions.
It uses the live Python.org API and can fail if that API is unavailable.

Before release, pilot check-only calls with the seven existing consumers' file
lists, then validate issue creation in a test repository. Duplicate detection,
consumer migrations, autopep8 onboarding, publishing a release,
and moving a major-version tag are separate rollout steps.
