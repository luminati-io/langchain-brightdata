"""Stop a PyPI release before upload when something is off.

    python scripts/release_guard.py --pr          # offline checks, for pull requests
    python scripts/release_guard.py --tag v0.2.1  # --pr checks plus release checks

Exit code 0 when every check passes. Exit code 1 otherwise, with one line per
failure that says what is wrong and what to do.

The workflow checks read the YAML line by line instead of parsing it, so the
script needs nothing beyond the standard library, packaging and (below Python
3.11) tomli. When a line is unclear they fail rather than pass.

pyproject.toml is read from the working tree, so run the guard before any step
that edits it. This script never ships: the hatch wheel and sdist settings in
pyproject.toml include only the package, README and LICENSE.
"""

import argparse
import functools
import http.client
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from packaging.version import InvalidVersion, Version

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

PACKAGE_NAME = "langchain-brightdata"
PYPI_URL = f"https://pypi.org/pypi/{PACKAGE_NAME}/json"
WORKFLOWS_DIR = Path(".github") / "workflows"
PUBLISH_FILE = "publish.yml"
PUBLISH_ACTION = "pypa/gh-action-pypi-publish"
WORKFLOW_REF_PREFIX = f"luminati-io/{PACKAGE_NAME}/.github/workflows/{PUBLISH_FILE}@"
# The full ref name: a tag called "origin/main" would win over the short name.
MAIN_REF = "refs/remotes/origin/main"
REPO_ROOT = Path(__file__).resolve().parents[1]

# [0-9] rather than \d: in Python, \d also matches non-ASCII digits.
TAG_PATTERN = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+(?:rc[0-9]+)?")

# A YAML comment starts with # at the start of a line or after whitespace.
_COMMENT = re.compile(r"(?:^|\s)#.*$")
# Matched case-insensitively, as GitHub matches action names and input names.
_ACTION_MENTION = re.compile(re.escape(PUBLISH_ACTION), re.IGNORECASE)
_USES_ACTION = re.compile(
    r"""\buses\s*:\s*["']?""" + re.escape(PUBLISH_ACTION) + r"""@[^\s"']+""", re.IGNORECASE
)
_CALLS_WORKFLOW = re.compile(
    r"""\buses\s*:\s*["']?(?:\./|luminati-io/"""
    + re.escape(PACKAGE_NAME)
    + r"""/)\.github/workflows/([^@\s"']+)""",
    re.IGNORECASE,
)
# The action accepts skip-existing and the older skip_existing.
_SKIP_EXISTING = re.compile(
    r"""(skip[-_]existing)["']?\s*:\s*("[^"]*"|'[^']*'|[^\s,}]*)""", re.IGNORECASE
)

Fetch = Callable[[str], bytes]
GitRunner = Callable[[Sequence[str]], Tuple[int, str]]


def _one_line(value: object) -> str:
    return " ".join(str(value).split())


def _strip_comments(text: str) -> List[str]:
    return [_COMMENT.sub("", line) for line in text.splitlines()]


def _parse_version(value: Any) -> Optional[Version]:
    if not isinstance(value, str):
        return None
    try:
        return Version(value)
    except InvalidVersion:
        return None


def read_workflows(root: Path) -> Dict[str, str]:
    """Return {file name: text} for every .yml and .yaml file in .github/workflows."""
    directory = root / WORKFLOWS_DIR
    if not directory.is_dir():
        return {}
    return {
        # GitHub requires UTF-8; replacing bad bytes still lets every check run.
        path.name: path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(directory.iterdir())
        if path.is_file() and path.suffix.lower() in (".yml", ".yaml")
    }


def load_project(root: Path) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """Return the [project] table of pyproject.toml, or None and the failure."""
    try:
        text = (root / "pyproject.toml").read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, ["pyproject.toml not found; run the guard on the repository root"]
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return None, [f"pyproject.toml is not valid TOML ({_one_line(exc)}); fix the file"]
    project = data.get("project")
    if not isinstance(project, dict):
        return None, ["pyproject.toml has no [project] table; add one with name and version"]
    return project, []


def check_publish_workflow_exists(workflows: Mapping[str, str]) -> List[str]:
    """publish.yml must exist under exactly that name."""
    if PUBLISH_FILE in workflows:
        return []
    return [f"{WORKFLOWS_DIR.as_posix()}/{PUBLISH_FILE} not found; "
            "the release workflow must have exactly that name"]


def check_publish_uses_action(publish_text: str) -> List[str]:
    """publish.yml must upload with a step that uses the PyPI publish action itself."""
    if any(_USES_ACTION.search(line) for line in _strip_comments(publish_text)):
        return []
    return [f"{PUBLISH_FILE} has no step that uses {PUBLISH_ACTION}@<ref>; "
            f"upload to PyPI from a step in {PUBLISH_FILE}"]


def check_no_skip_existing(publish_text: str) -> List[str]:
    """publish.yml must not set skip-existing to anything but false.

    The action treats every value other than "false" (any case) as on, so an
    empty value or an expression fails too.
    """
    failures = []
    for number, line in enumerate(_strip_comments(publish_text), start=1):
        for match in _SKIP_EXISTING.finditer(line):
            key, value = match.groups()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if value.lower() != "false":
                failures.append(
                    f"{PUBLISH_FILE} line {number} sets {key}; "
                    "remove it so uploading a version that is already on PyPI fails"
                )
    return failures


def check_single_publisher(workflows: Mapping[str, str]) -> List[str]:
    """No workflow but publish.yml may use the action, directly or through a reusable workflow.

    Only reusable workflows in this repository can be followed. The check fails
    on any mention of the action outside a comment, not just on a step.
    """
    lines = {name: _strip_comments(text) for name, text in workflows.items()}
    direct = {
        name for name, text in lines.items() if any(_ACTION_MENTION.search(x) for x in text)
    }
    calls = {
        name: {called for line in text for called in _CALLS_WORKFLOW.findall(line)}
        for name, text in lines.items()
    }
    uploaders = set(direct)
    # A workflow that calls an uploading workflow uploads too; repeat until nothing is added.
    added = True
    while added:
        added = False
        for name, called in calls.items():
            if name not in uploaders and called & uploaders:
                uploaders.add(name)
                added = True

    failures = []
    for name in sorted(uploaders - {PUBLISH_FILE}):
        if name in direct:
            failures.append(
                f"{name} also uses {PUBLISH_ACTION}; only {PUBLISH_FILE} may upload to PyPI"
            )
            continue
        for called in sorted(calls[name] & uploaders):
            failures.append(
                f"{name} calls {called}, which uploads to PyPI; "
                f"only {PUBLISH_FILE} may upload to PyPI"
            )
    return failures


def check_project_name(project: Mapping[str, Any]) -> List[str]:
    """[project].name must be exactly the published name."""
    name = project.get("name")
    if name == PACKAGE_NAME:
        return []
    shown = "missing" if name is None else name
    return [f"pyproject name is {shown}, expected {PACKAGE_NAME}; "
            f"set [project].name to {PACKAGE_NAME}"]


def check_project_version(project: Mapping[str, Any]) -> List[str]:
    """[project].version must be a canonical PEP 440 version."""
    version = project.get("version")
    if not isinstance(version, str):
        return ['pyproject has no [project].version string; '
                'set a static one like version = "0.2.1"']
    try:
        canonical = str(Version(version))
    except InvalidVersion:
        return [f"pyproject version {version} is not a valid PEP 440 version; "
                "use one like 0.2.1"]
    if canonical != version:
        return [f"pyproject version {version} is not canonical PEP 440; "
                f"write it as {canonical}"]
    return []


def check_tag_format(tag: str) -> List[str]:
    """The tag must be vX.Y.Z or vX.Y.ZrcN."""
    if TAG_PATTERN.fullmatch(tag):
        return []
    return [f"tag {tag} is not of the form vX.Y.Z or vX.Y.ZrcN; push a tag like v0.2.1"]


def check_tag_matches_version(tag: str, version: str) -> List[str]:
    """The tag without its leading v must equal the committed version exactly."""
    tag_version = tag[1:] if tag.startswith("v") else tag
    if tag_version == version:
        return []
    return [f"tag {tag} does not match pyproject {version}; "
            f"set [project].version to {tag_version} or tag v{version}"]


def fetch_url(url: str, timeout: float = 15.0) -> bytes:
    """GET url and return the body. Raises on any network or HTTP error."""
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read()


def check_not_on_pypi(version: str, fetch: Fetch) -> List[str]:
    """The version (a valid PEP 440 string) must not be on PyPI yet.

    Fails closed when PyPI cannot be read. Versions are compared as PEP 440
    versions, as PyPI does (0.2 equals 0.2.0).
    """
    try:
        body = fetch(PYPI_URL)
    except (OSError, http.client.HTTPException) as exc:
        return [f"could not reach PyPI to check {version} ({_one_line(exc)}); "
                "try again when PyPI is reachable"]
    bad_json = [f"PyPI returned bad JSON for {PACKAGE_NAME}; try again later"]
    try:
        releases = json.loads(body)["releases"]
    except (ValueError, KeyError, TypeError):
        return bad_json
    if not isinstance(releases, dict):
        return bad_json
    wanted = Version(version)
    if any(_parse_version(release) == wanted for release in releases):
        return [f"{version} is already on PyPI; bump [project].version and tag the new version"]
    return []


def check_workflow_ref(env: Mapping[str, str]) -> List[str]:
    """The run must come from publish.yml in the upstream repository."""
    ref = env.get("GITHUB_WORKFLOW_REF", "")
    if not ref:
        return ["GITHUB_WORKFLOW_REF is not set; "
                "run --tag only inside the publish workflow on GitHub Actions"]
    if ref.startswith(WORKFLOW_REF_PREFIX):
        return []
    return [f"workflow ref {ref} is not {PUBLISH_FILE} in luminati-io/{PACKAGE_NAME}; "
            f"release only from {WORKFLOWS_DIR.as_posix()}/{PUBLISH_FILE}"]


def run_git(args: Sequence[str], cwd: Path) -> Tuple[int, str]:
    """Run git in cwd and return (exit code, output)."""
    try:
        proc = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    return proc.returncode, (proc.stderr or proc.stdout).strip()


def check_head_on_main(git: GitRunner) -> List[str]:
    """The tagged commit (HEAD) must already be on origin/main."""
    code, output = git(["rev-parse", "--verify", "--quiet", f"{MAIN_REF}^{{commit}}"])
    if code == 1:
        return ["origin/main is not available; "
                "check out with fetch-depth: 0 so the guard can see main"]
    if code == 0:
        code, output = git(["merge-base", "--is-ancestor", "HEAD", MAIN_REF])
        if code == 0:
            return []
        if code == 1:
            return ["HEAD is not on main; tag a commit that is already on main"]
    return [f"could not check whether HEAD is on main (git exit {code}: {_one_line(output)}); "
            "check that the checkout is a full git clone"]


def pr_checks(root: Path) -> List[str]:
    """Offline checks of the workflows and pyproject.toml."""
    failures: List[str] = []
    workflows = read_workflows(root)
    failures += check_publish_workflow_exists(workflows)
    publish_text = workflows.get(PUBLISH_FILE)
    if publish_text is not None:
        failures += check_publish_uses_action(publish_text)
        failures += check_no_skip_existing(publish_text)
    failures += check_single_publisher(workflows)
    project, load_failures = load_project(root)
    failures += load_failures
    if project is not None:
        failures += check_project_name(project)
        failures += check_project_version(project)
    return failures


def tag_checks(
    root: Path, tag: str, env: Mapping[str, str], fetch: Fetch, git: GitRunner
) -> List[str]:
    """Every --pr check plus the checks for releasing tag."""
    failures = pr_checks(root)
    tag_failures = check_tag_format(tag)
    failures += tag_failures
    project, _ = load_project(root)  # pr_checks already reported a load failure
    version = project.get("version") if project is not None else None
    if isinstance(version, str) and not tag_failures:
        failures += check_tag_matches_version(tag, version)
    if _parse_version(version) is not None:
        failures += check_not_on_pypi(version, fetch)
    failures += check_workflow_ref(env)
    failures += check_head_on_main(git)
    return failures


def main(
    argv: Optional[Sequence[str]] = None,
    env: Optional[Mapping[str, str]] = None,
    fetch: Optional[Fetch] = None,
    git: Optional[GitRunner] = None,
) -> int:
    """Run the checks, print each failure on its own line, return the exit code."""
    parser = argparse.ArgumentParser(description="Check that a PyPI release is safe to upload.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--pr", action="store_true", help="offline checks for a pull request")
    mode.add_argument("--tag", metavar="TAG", help="every --pr check plus release checks for TAG")
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT,
        help="repository to check (default: the one this script is in)",
    )
    args = parser.parse_args(argv)

    if args.tag is None:
        failures = pr_checks(args.root)
    else:
        failures = tag_checks(
            args.root,
            args.tag,
            env=os.environ if env is None else env,
            fetch=fetch_url if fetch is None else fetch,
            git=functools.partial(run_git, cwd=args.root) if git is None else git,
        )

    for failure in failures:
        print(failure, file=sys.stderr)
    if failures:
        return 1
    print("All --pr checks passed." if args.tag is None else f"All checks passed for {args.tag}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
