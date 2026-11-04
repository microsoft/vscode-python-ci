# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import datetime
import html
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.error
import urllib.request

import yaml


DOWNLOADS_URL = (
    "https://www.python.org/api/v2/downloads/release/"
    "?is_published=true&pre_release=true&version=3"
)
RC_NAME = re.compile(r"Python (?P<series>3\.\d+)\.0rc\d+")
PYTHON_VERSION = re.compile(
    r"(?P<series>\d+\.\d+)(?:\.\d+)?"
    r"(?:(?:a|b|rc)\d+|(?:\.dev|dev)\d+|-dev)?"
)


def fetch_releases():
    request = urllib.request.Request(
        DOWNLOADS_URL, headers={"User-Agent": "pylance-engineering-python-version-check"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def latest_release_candidate(releases, now=None):
    if not isinstance(releases, list):
        raise ValueError("Expected a JSON array from the Python.org downloads API")
    now = now or datetime.datetime.now(datetime.timezone.utc)
    candidates = []
    for release in releases:
        if not isinstance(release, dict):
            continue
        if (
            release.get("is_published") is not True
            or release.get("pre_release") is not True
            or release.get("version") != 3
            or not isinstance(release.get("name"), str)
        ):
            continue
        match = RC_NAME.fullmatch(release["name"])
        if not match:
            continue
        try:
            date = datetime.datetime.fromisoformat(
                release["release_date"].replace("Z", "+00:00")
            )
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid release_date for {release['name']}") from exc
        if date.tzinfo is None:
            raise ValueError(f"Missing timezone in release_date for {release['name']}")
        if date <= now:
            candidates.append(match.group("series"))
    if not candidates:
        raise ValueError("The downloads API did not contain a released Python RC")
    return max(candidates, key=lambda series: tuple(map(int, series.split("."))))


def parse_files(files, workspace):
    entries = yaml.load(files, Loader=yaml.BaseLoader)
    if not isinstance(entries, list) or not entries:
        raise ValueError("files must be a nonempty YAML list of path/key entries")
    workspace = pathlib.Path(workspace).resolve(strict=True)
    workflows = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "key"}:
            raise ValueError("Each files entry must contain exactly path and key")
        name = entry["path"]
        key = entry["key"]
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Each workflow path must be a nonempty string")
        if not isinstance(key, str) or not key.strip():
            raise ValueError("Each matrix key must be a nonempty string")
        name = name.strip()
        key = key.strip()
        relative = pathlib.Path(name)
        if relative.is_absolute():
            raise ValueError(f"Workflow path must be relative to the checkout: {name}")
        path = (workspace / relative).resolve(strict=True)
        if not path.is_relative_to(workspace) or not path.is_file():
            raise ValueError(f"Workflow path must be a file inside the checkout: {name}")
        if (path, key) not in workflows:
            workflows.append((path, key))
    return workspace, workflows


def configured_matrices(workflow, key):
    # BaseLoader preserves scalars such as unquoted 3.10 without float conversion.
    document = yaml.load(workflow.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    if not isinstance(document, dict) or not isinstance(document.get("jobs"), dict):
        raise ValueError(f"Expected a jobs mapping in {workflow}")
    matrices = []
    for job_id, job in document["jobs"].items():
        context = f"key {key!r}, job {job_id!r} in {workflow}"
        if not isinstance(job, dict):
            raise ValueError(f"Expected a mapping for {context}")
        strategy = job.get("strategy", {})
        if not isinstance(strategy, dict):
            raise ValueError(f"Unsupported strategy for {context}")
        matrix = strategy.get("matrix", {})
        if not isinstance(matrix, dict):
            raise ValueError(f"Unsupported dynamic matrix for {context}")

        for modifier in ("include", "exclude"):
            entries = matrix.get(modifier, [])
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if isinstance(entry, dict) and key in entry:
                    raise ValueError(f"Unsupported Python matrix for {context}")

        if key not in matrix:
            continue
        if "include" in matrix or "exclude" in matrix:
            raise ValueError(f"Unsupported Python matrix for {context}")
        values = matrix[key]
        if not isinstance(values, list) or not values:
            raise ValueError(f"Expected a static Python version list for {context}")
        versions = set()
        for value in values:
            if value == "3.x":
                continue
            match = PYTHON_VERSION.fullmatch(value) if isinstance(value, str) else None
            if not match:
                raise ValueError(f"Unsupported Python version {value!r} for {context}")
            versions.add(match.group("series"))
        if versions:
            matrices.append((job_id, versions))
    if not matrices:
        raise ValueError(f"No explicit Python version matrices for key {key!r} in {workflow}")
    return matrices


def missing_matrices(latest, workflows, workspace):
    missing = []
    for workflow, key, matrices in workflows:
        filename = workflow.relative_to(workspace).as_posix()
        for job, versions in matrices:
            if latest not in versions:
                missing.append({"file": filename, "job": job, "key": key})
    return missing


def create_issue(repository, latest, missing, labels, token):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Expected GITHUB_REPOSITORY in owner/repository form")
    title = f"CI Python Versions: Update to Python {latest}"
    targets = "\n".join(
        f"- [ ] Add Python {latest} in `{item['file']}`, "
        f"job `{item['job']}`, key `{item['key']}`."
        for item in missing
    )
    body = f"""Python {latest} has a published release candidate according to the
[Python.org downloads API]({DOWNLOADS_URL}), but is missing from CI matrices.

### Requested changes
{targets}
- [ ] Run tests on Python {latest} and resolve compatibility failures.

Compare by major.minor; patch, prerelease, and dev variants count as coverage.
Add versions only where missing and preserve existing entries.
Keep minimum-supported-version and build-runtime pins unchanged.

This check evaluates declared matrix coverage, not installation settings or test results."""
    arguments = [
        "gh", "issue", "create",
        "--repo", repository,
        "--title", title,
        "--body", body,
    ]
    for label in labels.split(","):
        label = label.strip()
        if label:
            arguments.extend(["--label", label])
    env = {**os.environ, "GH_TOKEN": token, "GH_PROMPT_DISABLED": "1"}
    result = subprocess.run(
        arguments,
        env=env,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    return result.stdout.strip()


def publish_results(latest, missing, issue_url):
    outputs = {
        "latest-version": latest,
        "missing-matrices": json.dumps(missing, separators=(",", ":"), ensure_ascii=True),
        "issue-url": issue_url,
    }
    if any("\n" in value or "\r" in value for value in outputs.values()):
        raise ValueError("Action outputs must be single-line values")
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as output:
            for name, value in outputs.items():
                output.write(f"{name}={value}\n")
    summary = f"## CI Python version coverage\n\nLatest published RC series: **{latest}**.\n\n"
    if missing:
        summary += "Missing declared coverage:\n\n"
        for item in missing:
            summary += (
                f"- `{html.escape(item['file'])}` / `{html.escape(item['job'])}` "
                f"/ `{html.escape(item['key'])}`\n"
            )
    else:
        summary += "All explicit Python matrices in the supplied files declare coverage.\n"
    if issue_url:
        summary += f"\nIssue: {issue_url}\n"
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as output:
            output.write(summary)
    print(json.dumps(outputs))


def main():
    issue_mode = os.environ.get("CHECK_CREATE_ISSUE", "true")
    if issue_mode not in ("true", "false"):
        raise ValueError("create-issue must be true or false")
    issue_enabled = issue_mode == "true"
    token = os.environ.get("CHECK_TOKEN", "")
    if issue_enabled and not token:
        raise ValueError("token is required when create-issue is true")
    workspace, entries = parse_files(
        os.environ.get("CHECK_FILES", ""), os.environ["GITHUB_WORKSPACE"]
    )
    workflows = [
        (path, key, configured_matrices(path, key))
        for path, key in entries
    ]
    latest = latest_release_candidate(fetch_releases())
    missing = missing_matrices(latest, workflows, workspace)
    issue_url = ""
    if missing and issue_enabled:
        issue_url = create_issue(
            os.environ.get("GITHUB_REPOSITORY", ""),
            latest,
            missing,
            os.environ.get("CHECK_ISSUE_LABELS", ""),
            token,
        )
    publish_results(latest, missing, issue_url)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, yaml.YAMLError, subprocess.SubprocessError) as exc:
        print(f"Python version check failed: {exc}", file=sys.stderr)
        sys.exit(1)
