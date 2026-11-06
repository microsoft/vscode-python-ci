# Get next or previous extension version

Calculate a version without modifying the source manifest. This composite
action calls [get-extension-version](../get-extension-version/README.md), then
uses standard-library Python to calculate its single output, **`version`**.
It performs no checkout, Git operations, commits, or publication.

## Inputs

| Input                | Default        | Meaning                                                                 |
| -------------------- | -------------- | ----------------------------------------------------------------------- |
| `package-json-path`  | `package.json` | Manifest path, absolute or relative to the caller's workspace.          |
| `type`               | Required       | `pre-release` selects an odd minor; `release` selects an even minor.    |
| `strategy`           | Required       | Currently only `odd-even-minor`.                                        |
| `direction`          | `next`         | `next` selects a strictly higher minor; `previous` selects a lower one. |
| `pre-release-suffix` | Empty          | Optional prerelease identifiers, such as `dev` or `rc.1`.               |

## `odd-even-minor`

Select the nearest minor in the requested direction with the requested parity.
Move by two if the source minor already has that parity, otherwise by one.
Preserve major, reset patch to zero, and discard source prerelease/build
identifiers. The calculated major/minor must fit `0..2147483647`.

Append a nonempty `pre-release-suffix` only for `type: pre-release`. Supply it
without a leading `-` or build metadata. Empty means no suffix, even if the
source has one. `type: release` ignores this input and is always suffix-free.

Starting from `2026.9.7-dev+build`:

| Type          | Direction  | Suffix | Output          |
| ------------- | ---------- | ------ | --------------- |
| `pre-release` | `next`     | `dev`  | `2026.11.0-dev` |
| `pre-release` | `previous` | `rc.1` | `2026.7.0-rc.1` |
| `release`     | `next`     | Empty  | `2026.10.0`     |
| `release`     | `previous` | Empty  | `2026.8.0`      |

These are minor-selection rules, not SemVer patch increments. For example,
`1.44.7` with `type: release`, `direction: next` produces `1.46.0`, not
`1.44.8`. Unknown options, invalid applicable suffixes, and out-of-range results
fail. There is no calendar rollover or borrowing from the major:
`2027.1.0` can select previous release `2027.0.0`, but a previous prerelease
fails because it would need a negative minor.

## Usage

```yaml
steps:
  - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
  - id: next
    uses: microsoft/vscode-python-ci/actions/get-extension-next-version@<reviewed-commit-sha>
    with:
      type: pre-release
      strategy: odd-even-minor
      pre-release-suffix: dev
```

Read `${{ steps.next.outputs.version }}` in later steps. Set
`direction: previous` to select an earlier minor instead. A separate getter
step is unnecessary: this action already calls it.

Internal `$/` references keep the getter at the same repository/ref as this
action, including when a consumer pins a full commit SHA. This requires
GitHub.com and runner version **2.336.0 or newer**; GitHub Enterprise Server is
not supported. See [self-repository references](https://github.blog/changelog/2026-07-30-reference-same-repository-actions-with-self-repository-syntax/).

## Tests

```sh
python -m unittest discover -s actions/get-extension-next-version/tests -v
```

Focused tests cover both helpers, paths, read-only CLI outputs, direction/parity,
suffix handling, and invalid inputs/bounds. The release-action CI workflow also
smoke-tests the nested actions without checking out the automation repository.
