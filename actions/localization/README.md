# Localization

Export and submit English strings from a VS Code extension. The composite action
checks out the calling extension, sets up Node.js and Python, exports with pinned
`@vscode/l10n-dev@0.0.35`, and submits changed XLF to
`microsoft/vscode-python-extensions-loc`.

The standard-library Python helper also supports pull-only translation imports
from Azure Pipelines. No shared runtime-library adoption is required.

## GitHub Actions

```yaml
permissions:
  contents: read

jobs:
  localization:
    runs-on: ubuntu-latest
    steps:
      - uses: microsoft/vscode-python-ci/actions/localization@<reviewed-commit-sha>
        with:
          app-id: ${{ vars.PYTHON_LOCALIZATION_APP_ID }}
          private-key: ${{ secrets.PYTHON_LOCALIZATION_PRIVATE_KEY }}
          submodules: recursive
          source-paths: '["src", "external/vscode-common-python-lsp/typescript/src"]'
```

Keep trigger paths and concurrency in the caller workflow. The action performs
checkout itself. Omit `submodules` and use the default source paths for standalone
runtime extensions. Runtime extraction and import happen only when `package.json`
declares `l10n`; other extensions process manifest strings only.

| Input                 | Default                                      | Meaning                                                              |
| --------------------- | -------------------------------------------- | -------------------------------------------------------------------- |
| `app-id`              | Required                                     | GitHub App ID, normally `vars.PYTHON_LOCALIZATION_APP_ID`.           |
| `private-key`         | Required                                     | App private key, normally `secrets.PYTHON_LOCALIZATION_PRIVATE_KEY`. |
| `source-paths`        | `["src"]`                                    | JSON array of extraction directories inside the extension.           |
| `submodules`          | `false`                                      | Checkout submodules; use `recursive` for shared runtime sources.     |
| `node-version`        | `22.21.1`                                    | Node.js version used by the pinned localization CLI.                 |
| `npm-registry`        | `https://packagefeedproxy.microsoft.io/npm/` | Feed used by `npx`.                                                  |
| `localization-branch` | `dev`                                        | Existing localization repository branch for submissions.             |

This action has no outputs. It uses Python 3.10 and loads its helper from the
pinned action revision, not the caller's checkout. Source paths and branch values
are passed through quoted environment variables, not interpolated into scripts.

Configure credentials in the caller repository or grant it organization-level
access. The action mints an App token with Contents write permission scoped only
to `microsoft/vscode-python-extensions-loc`. Do not copy credentials into this
repository or broaden the caller's `GITHUB_TOKEN` permissions.

## English submission

Identity comes from `package.json`: `<publisher>.<name>`. English is submitted to
`src/en/<publisher>.<name>/<publisher>.<name>-new.xlf` on the existing configured
branch. A clean checkout on that branch is required. Only that extension's XLF
is staged; unchanged XLF succeeds without a commit.
If an earlier push failed, rerunning submission publishes the pending commit
instead of reporting a synchronized no-op.

Submissions use normal pushes, never force pushes. Concurrent updates allow up to
three push attempts with pull/rebase. The default flow does not modify `main`.

## Azure translation imports

Keep the `localizationTools` resource alias, checkout directory, translation
resource, and existing service connection. Change only the tooling repository
and reviewed commit:

```yaml
resources:
  repositories:
    - repository: localizationTools
      type: github
      name: microsoft/vscode-python-ci
      ref: <same-reviewed-commit-sha-as-the-github-action>
      endpoint: Github-Pylance
```

The helper stays at `scripts/localization.py`, so existing Pylance-Eng
stable/pre-release templates can keep their command unchanged. Continue enabling
`pullLocalization: true`; imports must run after caller build steps and before
VSIX packaging.

```text
python <tools>/scripts/localization.py --operation import \
  --extension-root <extension> --translations-root <drop>/out \
  --output-directory <new-staging-directory>
```

The importer derives `<drop>/out/<publisher>.<name>` automatically. It requires
all 14 locales: `cs`, `de`, `es`, `fr`, `it`, `ja`, `ko`, `pl`, `pt-br`,
`qps-ploc`, `ru`, `tr`, `zh-cn`, and `zh-tw`. `zh-Hans` and `zh-Hant` handbacks
map to `zh-cn` and `zh-tw`.

Missing, empty, malformed, duplicate, or incomplete handbacks fail. Runtime
extensions require both manifest and runtime tables. Untranslated strings and
wholly untranslated tables are allowed; English fallback is intentional.
When every target in a validated table is omitted, its generated JSON may be
`{}` so the extension uses its English fallback. Empty output for a table with
target elements still fails.
All handbacks and generated JSON are validated in a new staging directory outside
the extension before generated locale files are copied. Imports never submit
English or change tracked English `package.nls.json`.

Generated root `package.nls.<locale>.json` and declared runtime locale files
should be ignored by Git but included by VSCE.

## Standalone CLI

Requires Python 3.10 or newer, Git for submission, and Node.js/`npx` for export
and import. There are no third-party Python dependencies.

```sh
python scripts/localization.py --operation export \
  --extension-root <extension> --source-paths '["src"]' \
  --output-directory <new-english-staging-directory>

python scripts/localization.py --operation submit \
  --extension-root <extension> --output-directory <english-staging-directory> \
  --drop-root <localization-checkout> --branch dev
```

Set `NPM_CONFIG_REGISTRY` when using the CLI directly to select the npm feed.
Export/import staging directories must not already exist. The submit operation
uses the previously exported XLF.

## Validation and migration

```sh
python -m unittest discover -s scripts -p "*_test.py" -v
```

Regression tests use temporary files, mocked CLI calls, and local Git repositories.
Set `LOCALIZATION_CLI_SMOKE=1` to additionally run the real pinned CLI through
manifest-only, standalone-runtime, and shared-source export/import round trips.
These smoke tests use synthetic handbacks, verify all locales and English
fallback, require npm-feed access, and never authenticate or write to a live drop.
CI runs both suites on Linux and Windows with Python 3.10 and 3.13.

The helper and original regression tests were ported from
`microsoft/vscode-common-python-lsp@6b4a3573e7e7a9fe1e468e129544432278aec2d6`.
The composite action changes only the relative helper lookup for its new location.
Review fixes resolve relative handback paths, support all-omitted-target fallback,
and resume unpublished submissions after a failed push. Action inputs, defaults,
dependency pins, and CLI arguments remain unchanged.

Before migrating a caller, verify GitHub and Azure access to this repository.
Update its GitHub action and stable/pre-release Azure tooling references to the
same reviewed SHA. Keep source extraction paths and runtime-library submodules:
moving tooling does not move shared runtime source code.

autopep8's older `d1877b84bb10ff7caa6bd12ab4e75498ba760790` baseline rejects
wholly untranslated non-pseudo locale tables. Review that behavior alignment
separately before migrating it; this action follows the newer English-fallback
contract. Leave old tooling available until callers and relevant release branches
have migrated. Roll back by restoring both GitHub and Azure tooling references
together.
