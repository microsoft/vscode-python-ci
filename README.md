# TSA bug filing

TSA bug filing file has been configured: tsaoptions.json. Official builds are required to have TSA bug filing enabled by default. [Learn more](https://aka.ms/OBTSA)

# Introduction

TODO: Give a short introduction of your project. Let this section explain the objectives or the motivation behind this project.

# Getting Started

TODO: Guide users through getting your code up and running on their own system. In this section you can talk about:

1. Installation process
2. Software dependencies
3. Latest releases
4. API references

# Build and Test

## Extension localization

The public `azure-pipelines/extension/stable.yml` and `pre-release.yml` entry
points accept `pullLocalization: true` (default: false). This enables a shared
**pull-only** import immediately after caller build steps and before VSIX
packaging, so preparatory steps such as debugger pre-built copying cannot
overwrite the imported translations.

Consumers declare two GitHub repository resources using their authorized
`Github-Pylance` service connection:

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

Declare Pylance-Eng as `templates` and extend the appropriate public entry point.
Keep existing build, platform, registry, versioning, and validation parameters.
Use `sourceAnalysisPool` to preserve an existing caller's source-analysis pool.

The package job keeps extension source at `$(Pipeline.Workspace)/s`, and checks
out tools and translations in sibling `localization-tools` and
`localization-translations` folders. Only translation data is automatically
excluded from SDL source scanning. Extension source retains the default scan;
executable tooling is explicitly included.
`sourceRepositoriesToExclude` remains available for additional explicit
exclusions. Azure template expansion can persist checkout credentials; this
contract promises no release-side Git writes, not absence of persisted credentials.

The importer invokes the same pinned `scripts/localization.py` implementation
used by the common repository's English-push GitHub composite action. It derives
the extension ID and optional runtime directory from package.json, requires all
14 locales, and validates all staged files before placement. Every required
real-language manifest/runtime table must contain translation evidence; individual
untranslated strings are permitted. Manifest-only extensions remain manifest-only.
Missing or wholly untranslated handbacks fail explicitly.

English submission is a separate GitHub Actions workflow in each extension,
calling the shared composite action with explicitly configured app credentials.
Release pipelines do not extract English, acquire app write tokens, push to the
drop, or create translation-update PRs. Pin action and Azure tooling revisions
to the same reviewed common repository commit.

For validation, explicitly pass `publishExtension: false` to stable and
pre-release previews/test runs. Do not publish while onboarding or real
translated handbacks are still pending.

TODO: Describe and show how to build your code and run the tests.

# Contribute

TODO: Explain how other users and developers can contribute to make your code better.

If you want to learn more about creating good readme files then refer the following [guidelines](https://docs.microsoft.com/en-us/azure/devops/repos/git/create-a-readme?view=azure-devops). You can also seek inspiration from the below readme files:

- [ASP.NET Core](https://github.com/aspnet/Home)
- [Visual Studio Code](https://github.com/Microsoft/vscode)
- [Chakra Core](https://github.com/Microsoft/ChakraCore)
