# Copilot instructions for `pylance-eng`

## Build, test, and lint commands

This repository currently contains Azure Pipelines templates (not a local app/package with runnable build or test scripts).

- There is no checked-in `package.json`, `pyproject.toml`, `setup.cfg`, or test project in this repo root, so there is no local full-suite build/test/lint command to run from this repository alone.
- Pipeline templates show the operational commands used during CI/release:
  - Install dependencies: `npm ci` (`azure-pipelines/extension/templates/steps/sign.yml`)
  - Package VSIX: `npx @vscode/vsce@1.100.0 package ...` (`azure-pipelines/extension/templates/jobs/package.yml`)
  - Generate manifest: `npx @vscode/vsce@1.100.0 generate-manifest -i <vsix> -o <manifest>` (`azure-pipelines/extension/templates/steps/sign.yml`)
  - Verify one signed artifact (single-item check): `npx @vscode/vsce@1.100.0 verify-signature --packagePath <vsix> --manifestPath <manifest> --signaturePath <signature>` (`azure-pipelines/extension/templates/steps/sign.yml`)
  - Publish VSIX: `npx @vscode/vsce@latest publish ...` (documented in `azure-pipelines/extension/templates/steps/publish.yml`)

## High-level architecture

This repo is a reusable pipeline-template repository for VS Code extension packaging/signing/publishing in Azure DevOps.

- **Packaging layer**: `azure-pipelines/extension/templates/jobs/package.yml`
  - Iterates `buildPlatforms`
  - Sets `VSCETARGET`
  - Runs provided build steps
  - Produces per-platform VSIX artifacts (`vsix-<vsceTarget>` / `vsix-universal`)
- **Environment/bootstrap layer**: `azure-pipelines/extension/templates/steps/setup.yml`
  - Installs Node (default `22.17.0`) and Python (default `3.10`)
  - Configures custom npm registry/auth (including lockfile rewriting when needed)
- **Signing layer**: `azure-pipelines/extension/templates/steps/sign.yml`
  - Restores signing tool dependencies
  - Generates manifests
  - Signs via MicroBuild (`build/sign.proj`)
  - Optionally verifies signatures
- **Release orchestration layer**: `azure-pipelines/extension/templates/jobs/publish-extension.yml`
  - `Sign` job composes `sign.yml`
  - Optional `Publish` job composes `publish.yml`
  - Optional GitHub release/tag via `createGitHubRelease.yml`
- **Governance metadata**:
  - `owners.txt` for Ownership Enforcer reviewers
  - `.github/policies/pop.yml` and `es-metadata.yml` for org policy/compliance metadata

## Key repository conventions

- **Template-first design**: behavior is driven by YAML parameters and template composition, not by checked-in runtime source code.
- **Platform abstraction**: `buildPlatforms` entries use `{ name, vsceTarget }`; empty `vsceTarget` means **universal** and maps to artifact/folder names accordingly.
- **Artifact naming contract**:
  - Build artifacts: `vsix-<vsceTarget>` or `vsix-universal`
  - Signing outputs per platform folder include `extension.manifest` and `extension.signature.p7s`
- **Versioning convention** (pre-release standardized mode): patch version is `{YYYYMMDD}{RR}` from Azure DevOps build number (`modify-extension-version.yml`).
- **Registry/auth convention**: custom npm registry support is centralized in `steps/setup.yml`; lockfiles are rewritten to keep installs and `npx` on the same registry.
- **Compliance/approval convention**: changes in protected branches require approvers from applicable `owners.txt` entries.
- **Optional sister-repo scope**: only when explicitly requested, also apply corresponding updates to these repos: `vscode-python-debugger`, `vscode-pylint`, `vscode-isort`, `vscode-flake8`, `vscode-autopep8`, `vscode-mypy`, `vscode-black-formatter`; do not modify them by default.
