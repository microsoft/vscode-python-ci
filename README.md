# Pylance Engineering

Shared engineering automation for Pylance and related Python extension
repositories. This repository currently contains a Python-backed composite
GitHub Action for checking CI Python-version coverage, along with its tests and
validation workflow.

## Check CI Python versions

The [check-python-versions action](actions/check-python-versions/README.md)
compares caller-supplied workflow matrices with the newest Python 3 series that
has a published release candidate. It reports missing coverage and can open a
maintenance issue in the calling repository.

The action does not edit workflows, run extension tests, or change minimum
supported Python versions or build-runtime pins.

To use it:

1. Add a dedicated Ubuntu job in the calling repository.
2. Check out the caller's repository and invoke
   `microsoft/pylance-engineering/actions/check-python-versions@<reviewed-commit-sha>`.
3. Supply the workflow paths and Python matrix keys through the `files` input.
4. Start with `create-issue: 'false'` for check-only mode. For issue creation,
   provide a token with issue write access.

See the [action documentation](actions/check-python-versions/README.md) for a
complete workflow example, inputs, outputs, supported matrix forms, and failure
behavior. Issue mode currently creates a new issue on every run with missing
coverage; it does not detect duplicates.

## Repository contents

| Path | Purpose |
|---|---|
| [actions/check-python-versions/](actions/check-python-versions/) | Composite action definition, documentation, and pinned Python dependencies. |
| [scripts/check_python_versions.py](actions/check-python-versions/scripts/check_python_versions.py) | Release lookup, workflow matrix checks, reporting, and issue creation. |
| [tests/](actions/check-python-versions/tests/) | Unit tests and a representative workflow fixture. |
| [smoke-python-versions-action.yml](.github/workflows/smoke-python-versions-action.yml) | GitHub Actions smoke test and unit-test workflow. |

## Local development and validation

There is no compilation or packaging step. To use the same tooling Python
version as the action, set up Python 3.13, then run from the repository root:

```sh
python -m pip install -r actions/check-python-versions/requirements.txt
python -m unittest discover -s actions/check-python-versions/tests -v
```

The unit tests mock network and issue operations. The CI workflow also runs the
composite action in check-only mode against the fixture, using the live
Python.org API.

When changing the action, update its documentation and tests alongside the
implementation.
