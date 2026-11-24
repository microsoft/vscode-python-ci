# Check README tool version

Check that the bundled tool version stated in an extension's README matches the
version pinned in its `requirements.txt`. This composite action is read-only and
uses only Bash and GNU `grep`, so run it on a Linux runner.

## Inputs and output

| Input          | Default            | Meaning                                                        |
| -------------- | ------------------ | -------------------------------------------------------------- |
| `package`      | Required           | PyPI package name of the bundled tool, such as `pylint`.       |
| `readme`       | `README.md`        | README path, absolute or relative to the caller's workspace.   |
| `requirements` | `requirements.txt` | Requirements path, absolute or relative to the workspace.      |

**`version`** is the matching tool version.

## Matching rules

Each step runs one command:

1. Read the README version from `` ships with `<package>=<version>` ``; `==`
   is also accepted.
2. Read the pin from the line starting with `<package>==<version>`. Other pins,
   such as `isort` in Pylint's requirements or `mypy-extensions` in Mypy's, are
   ignored.
3. Fail unless the pin is nonempty and equals the README version.

The package name is matched literally. A missing file or match leaves a version
empty, which fails the comparison. Duplicate matches produce a multiline value,
which GitHub rejects when the step writes its output. A failed comparison emits
an error annotation on the README showing both versions, with `<none>` for a
missing value.

## Usage

```yaml
steps:
  - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
  - uses: microsoft/vscode-python-ci/actions/check-readme-tool-version@<reviewed-commit-sha>
    with:
      package: pylint
```

## Tests

The [smoke workflow](../../.github/workflows/smoke-check-readme-tool-version-action.yml)
runs the action against matching and mismatching fixtures in `tests/fixtures/`.
