# Check submodule updated

Check whether one submodule's **committed pin** equals the observed tip of an
upstream branch. This Bash-based composite action is read-only: it does not
initialize submodules, update files or Git configuration, fetch history, or
create commits and pull requests.

`action.yml` has separate steps for reading the committed pin, querying the
upstream branch, comparing the SHAs, and enforcing freshness. The steps call
small scripts under `scripts/`; the configured upstream URL stays within its
lookup step and is not passed through action outputs. No Python runtime or
packages are needed to run the action.

## Usage

```yaml
permissions:
  contents: read

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - name: Check shared library
        id: submodule
        uses: microsoft/vscode-python-ci/actions/check-submodule-updated@<reviewed-commit-sha>
        with:
          path: external/vscode-common-python-lsp
          branch: main
          fail-if-outdated: "false"
      - name: Report outdated pin
        if: steps.submodule.outputs.status == 'outdated'
        env:
          PINNED_SHA: ${{ steps.submodule.outputs.pinned-sha }}
          LATEST_SHA: ${{ steps.submodule.outputs.latest-sha }}
        run: |
          echo "Pinned: $PINNED_SHA"
          echo "Latest: $LATEST_SHA"
```

The caller must check out its repository at the workspace root. Submodule
initialization and full history are unnecessary. The action inspects the
checked-out parent commit, not the index, dirty `.gitmodules`, or the submodule
working directory's HEAD. It does not infer a different commit from event data.

## Inputs

| Input              | Default  | Description                                                                   |
| ------------------ | -------- | ----------------------------------------------------------------------------- |
| `path`             | Required | Exact submodule path relative to the repository root, without a trailing `/`. |
| `branch`           | `main`   | Upstream branch name, not a tag or full ref.                                  |
| `fail-if-outdated` | `"true"` | `"false"` reports an outdated pin without failing the step.                   |

Use the path recorded in `.gitmodules`; the submodule's name may differ.
Inputs must follow this documented format. No automatic discovery or update
behavior is provided.

## Outputs and failures

| Output       | Description                                          |
| ------------ | ---------------------------------------------------- |
| `status`     | Exactly `current` or `outdated`.                     |
| `pinned-sha` | Full submodule commit recorded in the parent commit. |
| `latest-sha` | Full upstream branch tip observed during this check. |

Outputs and a job summary are written before enforcing an outdated result.
Default enforcement fails the step when the SHAs differ; report-only mode
leaves that decision to subsequent steps.

Missing paths, non-submodule entries, missing configuration or branches, and
authentication/network failures fail in either mode. Outputs are not guaranteed
on errors; errors do not produce a third status.

## Requirements and limitations

- Bash and Git 2.36 or newer must be on `PATH`. GitHub-hosted Linux, Windows, and
  macOS runners provide them; self-hosted runners must supply them. Linux and
  Windows are covered by this action's CI.
- The committed `.gitmodules` URL must be an absolute Git URL or absolute local
  path. Relative submodule URLs are not resolved against the parent origin.
- Authentication uses the caller's existing Git configuration. Public HTTPS
  repositories need no additional credentials. For private upstreams, configure
  access before invoking the action; the caller's token may not grant access to
  a different repository. No write permission is needed. Interactive Git
  credential prompts are disabled.
- `current` means equality **at check time**, not necessarily at merge time.
  Upstream changes do not automatically rerun downstream workflows.
- Freshness is not a compatibility guarantee. A deliberately older pin or a
  newer commit not yet at the selected branch tip is reported as `outdated`.
- On GitHub.com, the smoke workflow's `$/` sibling-action references require
  runner 2.336.0 or newer, consistent with the repository's other smoke tests.

## Local validation

From the repository root, with Python 3, Bash, and Git available:

```sh
python -m unittest discover -s actions/check-submodule-updated/tests -v
```

The tests invoke the same Bash helper scripts as the action against temporary
local Git repositories, checking outputs, enforcement, failures, and unchanged
repository state. The Python test harness uses only the standard library; the
tests need no network access, GitHub credentials, or additional packages.
Hosted composite smoke tests remain the integration check for the action
wrapper and actual GitHub runner behavior.
