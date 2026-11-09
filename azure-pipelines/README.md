# Extension release pipelines

These templates were imported from Pylance-Eng at commit
`8f562bf0d90d76baa4b5fb3dad2649f3287a8f9e`. Template paths, parameters,
artifact names, and release behavior are preserved.

## Consumer setup

Declare this GitHub repository with the literal resource alias `templates`.
Internal template references use that alias, including when extending the
MicroBuild template.

```yaml
resources:
  repositories:
    - repository: templates
      type: github
      name: microsoft/vscode-python-ci
      ref: <reviewed-commit-sha>
      endpoint: Github-Pylance

extends:
  template: /azure-pipelines/extension/stable.yml@templates
  parameters:
    teamName: <existing-signing-team>
    publishExtension: false
    buildSteps:
      - script: npm ci
      - script: npm run build
```

Use `/azure-pipelines/extension/pre-release.yml@templates` for pre-release
builds. When migrating an existing consumer, change its repository resource
from Pylance-Eng to this repository and pin a reviewed commit. Keep its existing
build steps, platform list, registry, versioning, and validation parameters.
Use `sourceAnalysisPool` to preserve an existing caller's source-analysis pool.

The templates still run in Azure DevOps and extend the internal
`1ESPipelineTemplates/MicroBuildTemplate` repository. Consumers need access to
the configured agent pools, internal package feeds, MicroBuild signing
services, and Marketplace/GitHub service connections. The GitHub service
connection must be authorized for this repository. No credentials are included
in these templates.

Caller build steps must prepare the extension and install its local `vsce`
dependency before packaging. The signing job expects `packages.config`,
`build/NuGet.config`, `build/sign.proj`, and npm dependency manifests in the
consumer repository. The files in [`tools/signing/`](../tools/signing/) are
supporting files for that consumer setup, not automatically checked-out or
staged signing dependencies.

Publishing defaults to `false` in both entry points. Stable releases require
manual validation before the publish stage. Pre-release standardized versioning
derives the patch version from the Azure DevOps build number (`YYYYMMDD.R`).
For onboarding and preview runs, explicitly keep `publishExtension: false`;
do not enable publishing until the consumer's release setup has been validated.

## Extension localization

Both entry points accept `pullLocalization: true` (default: `false`). This
enables a pull-only import after caller build steps and before VSIX packaging,
so preparatory steps such as debugger pre-built copying cannot overwrite the
imported translations.

Consumers declare two additional GitHub repository resources using their
authorized `Github-Pylance` service connection:

```yaml
resources:
  repositories:
    - repository: translations
      type: github
      name: microsoft/vscode-python-extensions-loc
      ref: refs/heads/dev
      endpoint: Github-Pylance
    - repository: localizationTools
      type: github
      name: microsoft/vscode-common-python-lsp
      ref: <reviewed-commit-sha>
      endpoint: Github-Pylance
```

Add these alongside the `templates` resource, not instead of it. The package
job keeps extension source at `$(Pipeline.Workspace)/s` and checks out tools
and translations in sibling `localization-tools` and
`localization-translations` folders. Only translation data is automatically
excluded from SDL source scanning. Extension source retains the default scan;
executable tooling is explicitly included. `sourceRepositoriesToExclude`
remains available for additional explicit exclusions. Azure template expansion
can persist checkout credentials; this contract promises no release-side Git
writes, not absence of persisted credentials.

The importer invokes the pinned `scripts/localization.py` implementation from
the common repository. It derives the extension ID and optional runtime
directory from `package.json`, requires all 14 locales, and validates all
staged files before placement. Every required real-language manifest/runtime
table must contain translation evidence; individual untranslated strings are
permitted. Manifest-only extensions remain manifest-only. Missing or wholly
untranslated handbacks fail explicitly.

English submission is a separate GitHub Actions workflow in each extension,
calling the shared composite action with explicitly configured app credentials.
Release pipelines do not extract English, acquire app write tokens, push to the
drop, or create translation-update PRs. Pin action and Azure tooling revisions
to the same reviewed common repository commit.

## Layout and validation

| Path | Purpose |
|---|---|
| `extension/stable.yml` | Stable build, manual validation, and opt-in publish entry point. |
| `extension/pre-release.yml` | Pre-release build and opt-in publish entry point. |
| `extension/templates/pipeline.yml` | Shared MicroBuild pipeline orchestration. |
| `extension/templates/jobs/` | Per-platform packaging and signing/publishing jobs. |
| `extension/templates/steps/` | Setup, versioning, localization, signing, publishing, and GitHub release steps. |

Build artifacts are named `vsix-<vsceTarget>` or `vsix-universal`. Signing
outputs include `extension.manifest` and `extension.signature.p7s` in each
platform folder.

There is no standalone local build for these templates. YAML parsing and
template-reference checks do not replace Azure DevOps template expansion or a
non-publishing consumer pipeline run with the required internal resources.
