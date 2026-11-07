# Get extension version

Read a manifest's current SemVer version or calculate its next/previous version. This
Python-backed composite action is read-only and has no third-party Python
dependencies. It does not check out code or invoke Git or GitHub APIs.

## Input and output

| Input                | Default                        | Meaning                                                                     |
| -------------------- | ------------------------------ | --------------------------------------------------------------------------- |
| `package-json-path`  | `package.json`                 | Manifest path, absolute or relative to the caller's workspace. Spaces work. |
| `mode`               | `current`                      | Return the unchanged version, or select a `next`/`previous` minor.          |
| `type`               | Required in every mode        | `pre-release` selects an odd minor; `release` selects an even minor.        |
| `strategy`           | Required in every mode        | Currently only `odd-even-minor`.                                            |
| `pre-release-suffix` | Empty                          | Optional prerelease identifiers without a leading `-` or build metadata.    |

**`version`** is the unchanged source version in `current` mode, including
prerelease/build identifiers, or the calculated version in `next`/`previous` mode.
Missing files, invalid JSON (including duplicate keys and
non-finite numbers), and missing/invalid SemVer versions fail the action.
`current` requires valid `type`/`strategy` values but ignores them and any suffix, and
does not impose an odd/even minor policy or Marketplace numeric bounds.
Missing, empty, or unsupported `type`/`strategy` values are rejected by the CLI
in every mode.

## `odd-even-minor`

Select the nearest minor in the requested direction with the requested parity.
Move by two if the source minor already has that parity, otherwise by one.
Preserve major, reset patch to zero, and discard source prerelease/build
identifiers. The calculated major/minor must fit `0..2147483647`.

Append a nonempty `pre-release-suffix` only for `type: pre-release`. Empty means
no suffix, even if the source has one. `type: release` ignores this input and
is always suffix-free.

Starting from `2026.9.7-dev+build`:

| Mode       | Type          | Suffix  | Output               |
| ---------- | ------------- | ------- | -------------------- |
| `current`  | Ignored       | Ignored | `2026.9.7-dev+build` |
| `next`     | `pre-release` | `dev`   | `2026.11.0-dev`      |
| `previous` | `pre-release` | `rc.1`  | `2026.7.0-rc.1`      |
| `next`     | `release`     | Empty   | `2026.10.0`          |
| `previous` | `release`     | Empty   | `2026.8.0`           |

These are minor-selection rules, not SemVer patch increments. For example,
`1.44.7` with `type: release`, `mode: next` produces `1.46.0`, not `1.44.8`.
Unknown modes, invalid applicable suffixes, and out-of-range results fail.
There is no calendar rollover or borrowing from the major: `2027.1.0` can
select previous release `2027.0.0`, but a previous prerelease fails because
it would need a negative minor.

## Usage

```yaml
steps:
  - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
  - id: current
    uses: microsoft/vscode-python-ci/actions/get-extension-version@<reviewed-commit-sha>
    with:
      package-json-path: package.json
      type: pre-release
      strategy: odd-even-minor
  - id: next
    uses: microsoft/vscode-python-ci/actions/get-extension-version@<reviewed-commit-sha>
    with:
      mode: next
      type: pre-release
      strategy: odd-even-minor
      pre-release-suffix: dev
```

Read `${{ steps.current.outputs.version }}` in subsequent steps. Omit
`package-json-path` for the root manifest, or point it at another package or a
temporary snapshot. The caller must provide the manifest; the action's Python
code comes from the pinned action repository, not the caller's checkout.
Use `${{ steps.next.outputs.version }}` for the calculated value, or set
`mode: previous` to select an earlier minor. The same action supports both
channels in either direction.

The Python CLI accepts the same options through `argparse`:

```sh
python actions/get-extension-version/scripts/extension_version.py \
  --type=pre-release --strategy=odd-even-minor
python actions/get-extension-version/scripts/extension_version.py \
  --package-json-path="path with spaces/package.json" \
  --mode=previous --type=release --strategy=odd-even-minor
```

The action forwards quoted shell variables as arguments rather than reading
configuration from the Python process's environment. `GITHUB_OUTPUT` remains
the standard GitHub Actions output channel.

## Tests

```sh
python -m unittest discover -s actions/get-extension-version/tests -v
```

Focused tests cover paths, read-only outputs, mode dispatch, direction/parity,
suffix handling, and invalid inputs/bounds. The release-action CI workflow also
smoke-tests all three modes without checking out the automation repository.
