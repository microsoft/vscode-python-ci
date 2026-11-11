# Pylance Engineering

Shared engineering automation for Pylance and related Python extension
repositories. This repository contains composite GitHub Actions
for checking CI Python-version coverage, reading/calculating extension versions,
preparing extension release branches, and submitting English localization,
along with their tests and validation workflows. It also provides a Bash-backed
submodule freshness check.

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

## Localization

The [localization action](actions/localization/README.md) exports English strings
and submits changed XLF to the localization repository. Its standalone Python
helper also imports validated translation handbacks during Azure packaging.
Pin the GitHub action and Azure tooling resource to the same reviewed commit.

The helper remains at `scripts/localization.py` for compatibility with existing
shared Azure templates. Caller credentials, extraction sources, and localization
data remain in their current repositories.

## Submodule freshness

The [check-submodule-updated action](actions/check-submodule-updated/README.md)
compares one committed submodule pin with the observed tip of an upstream branch.
It returns `current` or `outdated`, with optional report-only behavior. Git and
configuration errors always fail.

The action uses Bash and Git only. It does not initialize or update submodules,
change repository state, or integrate with release preparation automatically.

## Repository contents

| Path                                                                                               | Purpose                                                                            |
| -------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| [actions/check-python-versions/](actions/check-python-versions/)                                   | Composite action definition, documentation, and pinned Python dependencies.        |
| [scripts/check_python_versions.py](actions/check-python-versions/scripts/check_python_versions.py) | Release lookup, workflow matrix checks, reporting, and issue creation.             |
| [tests/](actions/check-python-versions/tests/)                                                     | Unit tests and a representative workflow fixture.                                  |
| [smoke-python-versions-action.yml](.github/workflows/smoke-python-versions-action.yml)             | GitHub Actions smoke test and unit-test workflow.                                  |
| [actions/get-extension-version/](actions/get-extension-version/README.md)                          | Read the current version or calculate the next/previous prerelease/stable version. |
| [actions/release-pr/](actions/release-pr/README.md)                                                | Validate version-only PRs and atomically create stable release branches.           |
| [smoke-release-pr-action.yml](.github/workflows/smoke-release-pr-action.yml)                       | Cross-platform release-action tests and read-only composite smoke test.            |
| [actions/localization/](actions/localization/README.md)                                            | English export/submission action and translation-import documentation.             |
| [scripts/localization.py](scripts/localization.py)                                                 | Shared standalone localization CLI for GitHub Actions and Azure Pipelines.         |
| [scripts/localization_test.py](scripts/localization_test.py)                                       | Localization regression tests, including local Git submissions.                    |
| [scripts/localization_smoke_test.py](scripts/localization_smoke_test.py)                           | Opt-in real CLI export/import round trips using synthetic handbacks.               |
| [smoke-localization-action.yml](.github/workflows/smoke-localization-action.yml)                   | Linux/Windows localization tests and credential-free real CLI validation.          |
| [actions/check-submodule-updated/](actions/check-submodule-updated/README.md)                       | Read-only Bash action comparing one submodule pin with an upstream branch tip.      |
| [smoke-check-submodule-updated-action.yml](.github/workflows/smoke-check-submodule-updated-action.yml) | Linux/Windows Bash regression tests and composite action smoke tests.             |

## Local development and validation

There is no compilation or packaging step. To use the same tooling Python
version as the action, set up Python 3.13, then run from the repository root:

```sh
python -m pip install -r actions/check-python-versions/requirements.txt
python -m unittest discover -s actions/check-python-versions/tests -v
python -m unittest discover -s actions/get-extension-version/tests -v
python -m unittest discover -s actions/release-pr/tests -v
python -m unittest discover -s scripts -p "*_test.py" -v
```

The Python-version tests mock network and issue operations; the release tests
use temporary local Git repositories. The version action uses only Python's standard
library and is tested without modifying manifests. The release action's sibling
reference requires GitHub.com and runner 2.336.0 or newer for `$/` references.
The Python-version CI workflow also runs
the composite action in check-only mode against the fixture, using the live
Python.org API.

Localization supports Python 3.10 or newer and has no third-party Python
dependencies. Its default tests are offline; set `LOCALIZATION_CLI_SMOKE=1`
to include the pinned npm CLI round trips run by localization CI.

When changing the action, update its documentation and tests alongside the
implementation.

The submodule freshness action requires no Python or package installation:

```sh
bash actions/check-submodule-updated/tests/test.sh
```
