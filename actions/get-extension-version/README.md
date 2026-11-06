# Get extension version

Read a manifest's top-level SemVer string and return it unchanged. This
Python-backed composite action is read-only and has no third-party Python
dependencies. It does not check out code or invoke Git or GitHub APIs.

## Input and output

| Input               | Default        | Meaning                                                                     |
| ------------------- | -------------- | --------------------------------------------------------------------------- |
| `package-json-path` | `package.json` | Manifest path, absolute or relative to the caller's workspace. Spaces work. |

**`version`** preserves the complete source version, including prerelease and
build identifiers. Missing files, invalid JSON (including duplicate keys and
non-finite numbers), and missing/invalid SemVer versions fail the action.
Reading does not impose an odd/even minor policy or Marketplace numeric bounds.

## Usage

```yaml
steps:
  - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
  - id: current
    uses: microsoft/vscode-python-ci/actions/get-extension-version@<reviewed-commit-sha>
    with:
      package-json-path: package.json
```

Read `${{ steps.current.outputs.version }}` in subsequent steps. Omit
`package-json-path` for the root manifest, or point it at another package or a
temporary snapshot. The caller must provide the manifest; the action's Python
code comes from the pinned action repository, not the caller's checkout.

## Tests

The shared version-action tests live with the calculator:

```sh
python -m unittest discover -s actions/get-extension-next-version/tests -v
```
