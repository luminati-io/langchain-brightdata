"""Stop a PyPI release before upload when something is off.

    python scripts/release_guard.py --pr          # offline checks, for pull requests
    python scripts/release_guard.py --tag v0.2.1  # --pr checks plus release checks

Exit code 0 when every check passes. Exit code 1 otherwise, with one line per
failure that says what is wrong and what to do.

The workflow and action checks read the YAML line by line instead of parsing
it, so the script needs nothing beyond the standard library, packaging and
(below Python 3.11) tomli. Each check leans toward failing: the checks for
something forbidden skip only full-line comments and decode YAML hex escapes,
and the check for the upload step ignores anything after a #. Not caught: a
name split over two lines of a double-quoted string.

pyproject.toml is read from the working tree, so run the guard before any step
that edits it. This script never ships: the hatch wheel and sdist settings in
pyproject.toml include only the package, README and LICENSE.
"""

import argparse
import functools
import http.client
import json
import os
import posixpath
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
REPO_SLUG = f"luminati-io/{PACKAGE_NAME}"
# The Simple API lists every version; the JSON API's "releases" key is deprecated.
PYPI_SIMPLE_URL = f"https://pypi.org/simple/{PACKAGE_NAME}/"
PYPI_SIMPLE_JSON = "application/vnd.pypi.simple.v1+json"
WORKFLOWS_DIR = ".github/workflows"
ACTIONS_DIR = ".github/actions"
ACTION_FILES = ("action.yml", "action.yaml")
PUBLISH_FILE = "publish.yml"
PUBLISH_PATH = f"{WORKFLOWS_DIR}/{PUBLISH_FILE}"
PUBLISH_ACTION = "pypa/gh-action-pypi-publish"
WORKFLOW_REF_PREFIX = f"{REPO_SLUG}/{PUBLISH_PATH}@refs/tags/"
# The full ref name: a tag called "origin/main" would win over the short name.
MAIN_REF = "refs/remotes/origin/main"
REPO_ROOT = Path(__file__).resolve().parents[1]

# [0-9] rather than \d: in Python, \d also matches non-ASCII digits.
VERSION_PATTERN = r"[0-9]+\.[0-9]+\.[0-9]+(?:rc[0-9]+)?"
_VERSION = re.compile(VERSION_PATTERN)
_TAG = re.compile("v" + VERSION_PATTERN)

# A YAML comment starts with # at the start of a line or after whitespace.
_COMMENT = re.compile(r"(?:^|\s)#.*$")
_HEX_ESCAPE = re.compile(r"\\x([0-9A-Fa-f]{2})|\\u([0-9A-Fa-f]{4})|\\U([0-9A-Fa-f]{8})")
# Matched case-insensitively, as GitHub matches action names and input names.
_ACTION_MENTION = re.compile(re.escape(PUBLISH_ACTION), re.IGNORECASE)
_USES_ACTION = re.compile(
    r"""\buses\s*:\s*["']?""" + re.escape(PUBLISH_ACTION) + r"""@[^\s"']+""", re.IGNORECASE
)
_USES = re.compile(r"""\buses\s*:\s*["']?([^\s"',}]+)""", re.IGNORECASE)
# The action reads skip-existing and the older skip_existing.
_SKIP_EXISTING = re.compile(r"skip[-_]existing", re.IGNORECASE)
_SKIP_EXISTING_OFF = re.compile(
    r"""\s*skip[-_]existing\s*:\s*(?:false|"false"|'false')(?:\s+#.*)?\s*""", re.IGNORECASE
)

Fetch = Callable[[str], bytes]
GitRunner = Callable[[Sequence[str]], Tuple[int, str]]


def _one_line(value: object) -> str:
    return " ".join(str(value).split())


def _read(path: Path) -> str:
    # GitHub requires UTF-8; replacing bad bytes still lets every check run.
    return path.read_text(encoding="utf-8", errors="replace")


def _strip_comments(text: str) -> List[str]:
    """Lines with comments cut off.

    A # inside a quoted value is cut too, so use this only where cutting too
    much makes a check fail, not pass.
    """
    return [_COMMENT.sub("", line) for line in text.splitlines()]


def _hex_char(match: "re.Match[str]") -> str:
    code = int(match.group(1) or match.group(2) or match.group(3), 16)
    return chr(code) if code <= 0x10FFFF else match.group(0)


def _scan_lines(text: str) -> List[str]:
    """Lines to search for something forbidden.

    Full-line comments become empty (line numbers stay right), YAML hex escapes
    such as the one for "-" are decoded, and nothing else is cut.
    """
    return [
        "" if line.lstrip().startswith("#") else _HEX_ESCAPE.sub(_hex_char, line)
        for line in text.splitlines()
    ]


def _local_target(value: str) -> Optional[str]:
    """The repo-relative path a uses: value points at in this repository, or None."""
    if value.startswith("./"):
        path = value[2:]
    elif value.lower().startswith((REPO_SLUG + "/", REPO_SLUG + "@")):
        path = value[len(REPO_SLUG):].split("@", 1)[0]
    else:
        return None
    # Normalise under a stand-in root so ".." cannot leave the repository.
    return posixpath.normpath("/" + path).lstrip("/")


def _call_targets(lines: Sequence[str]) -> List[str]:
    """Repo-relative files that uses: lines may call: a workflow, or an action's action.yml."""
    targets = []
    for line in lines:
        for value in _USES.findall(line):
            path = _local_target(value)
            if path is None:
                continue
            if path.lower().endswith((".yml", ".yaml")):
                targets.append(path)
            else:
                targets.extend(f"{path}/{name}" if path else name for name in ACTION_FILES)
    return targets


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
        path.name: _read(path)
        for path in sorted(directory.iterdir())
        if path.is_file() and path.suffix.lower() in (".yml", ".yaml")
    }


def read_upload_files(root: Path, workflows: Mapping[str, str]) -> Dict[str, str]:
    """Return {repo-relative path: text} for the workflows and every local action.

    Local actions are action.yml and action.yaml anywhere under .github/actions,
    plus any other action that these files call with uses: ./path.
    """
    files = {f"{WORKFLOWS_DIR}/{name}": text for name, text in workflows.items()}
    actions = root / ACTIONS_DIR
    if actions.is_dir():
        for path in sorted(actions.rglob("*")):
            if path.is_file() and path.name.lower() in ACTION_FILES:
                files[path.relative_to(root).as_posix()] = _read(path)
    pending = list(files)
    while pending:
        for target in _call_targets(_scan_lines(files[pending.pop()])):
            if target not in files and (root / target).is_file():
                files[target] = _read(root / target)
                pending.append(target)
    return files


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
    return [f"{PUBLISH_PATH} not found; the release workflow must have exactly that name"]


def check_publish_uses_action(publish_text: str) -> List[str]:
    """publish.yml must upload with a step that uses the PyPI publish action itself."""
    if any(_USES_ACTION.search(line) for line in _strip_comments(publish_text)):
        return []
    return [f"{PUBLISH_FILE} has no step that uses {PUBLISH_ACTION}@<ref>; "
            f"upload to PyPI from a step in {PUBLISH_FILE}"]


def check_no_skip_existing(publish_text: str) -> List[str]:
    """publish.yml may mention skip-existing only in a plain skip-existing: false line.

    The action treats every value other than "false" (any case) as on. Any
    other line outside a full-line comment that names skip-existing or
    skip_existing, in any case, fails: an expression, an empty value, an
    explicit ? key, a hex-escaped name or a flow mapping.
    """
    failures = []
    raw_lines = publish_text.splitlines()
    for number, (raw, line) in enumerate(zip(raw_lines, _scan_lines(publish_text)), start=1):
        match = _SKIP_EXISTING.search(line)
        if match and not _SKIP_EXISTING_OFF.fullmatch(raw):
            failures.append(
                f"{PUBLISH_FILE} line {number} sets {match.group(0)}; "
                "remove it so uploading a version that is already on PyPI fails"
            )
    return failures


def check_single_publisher(files: Mapping[str, str]) -> List[str]:
    """Only publish.yml may use the publish action, directly or through what it calls.

    files maps the repo-relative paths of workflows and local actions to their
    text (see read_upload_files). Any mention of the action outside a full-line
    comment counts as a use. Reusable workflows and actions in other
    repositories cannot be followed.
    """
    lines = {path: _scan_lines(text) for path, text in files.items()}
    direct = {
        path for path, text in lines.items() if any(_ACTION_MENTION.search(x) for x in text)
    }
    calls = {path: set(_call_targets(text)) & set(files) for path, text in lines.items()}
    uploaders = set(direct)
    # Whatever calls an uploader uploads too; repeat until nothing is added.
    added = True
    while added:
        added = False
        for path, called in calls.items():
            if path not in uploaders and called & uploaders:
                uploaders.add(path)
                added = True

    failures = []
    for path in sorted(uploaders - {PUBLISH_PATH}):
        if path in direct:
            failures.append(
                f"{path} also uses {PUBLISH_ACTION}; only {PUBLISH_FILE} may upload to PyPI"
            )
            continue
        for called in sorted(calls[path] & uploaders):
            failures.append(
                f"{path} calls {called}, which uploads to PyPI; "
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
    """[project].version must be canonical PEP 440 and of a form a release tag can have."""
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
    if not _VERSION.fullmatch(version):
        return [f"pyproject version {version} is not X.Y.Z or X.Y.ZrcN, so no release tag "
                "can match it; use a version like 0.2.1"]
    return []


def check_tag_format(tag: str) -> List[str]:
    """The tag must be vX.Y.Z or vX.Y.ZrcN."""
    if _TAG.fullmatch(tag):
        return []
    return [f"tag {tag} is not of the form vX.Y.Z or vX.Y.ZrcN; push a tag like v0.2.1"]


def check_tag_matches_version(tag: str, version: str) -> List[str]:
    """The tag without its leading v must equal the committed version exactly."""
    tag_version = tag[1:] if tag.startswith("v") else tag
    if tag_version == version:
        return []
    return [f"tag {tag} does not match pyproject {version}; "
            f"set [project].version to {tag_version} or tag v{version}"]


def fetch_simple_index(url: str, timeout: float = 15.0) -> bytes:
    """GET url from the PyPI Simple API as JSON. Raises on any network or HTTP error."""
    request = urllib.request.Request(url, headers={"Accept": PYPI_SIMPLE_JSON})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def check_not_on_pypi(version: str, fetch: Fetch) -> List[str]:
    """The version (a valid PEP 440 string) must not be on PyPI yet.

    Fails closed when PyPI cannot be read. Versions are compared as PEP 440
    versions, as PyPI does (0.2 equals 0.2.0).
    """
    try:
        body = fetch(PYPI_SIMPLE_URL)
    except (OSError, http.client.HTTPException) as exc:
        return [f"could not reach PyPI to check {version} ({_one_line(exc)}); "
                "try again when PyPI is reachable"]
    bad_json = [f"PyPI returned bad JSON for {PACKAGE_NAME}; try again later"]
    try:
        versions = json.loads(body)["versions"]
    except (ValueError, KeyError, TypeError):
        return bad_json
    if not isinstance(versions, list) or not all(isinstance(v, str) for v in versions):
        return bad_json
    wanted = Version(version)
    if any(_parse_version(release) == wanted for release in versions):
        return [f"{version} is already on PyPI; bump [project].version and tag the new version"]
    return []


def check_workflow_ref(env: Mapping[str, str], tag: str) -> List[str]:
    """The run must be publish.yml in the upstream repository, started by this tag."""
    ref = env.get("GITHUB_WORKFLOW_REF", "")
    if not ref:
        return ["GITHUB_WORKFLOW_REF is not set; "
                "run --tag only inside the publish workflow on GitHub Actions"]
    expected = WORKFLOW_REF_PREFIX + tag
    if ref == expected:
        return []
    return [f"workflow ref {ref} is not {expected}; "
            f"release only from {PUBLISH_FILE}, started by pushing tag {tag}"]


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
    """Offline checks of the workflows, local actions and pyproject.toml."""
    failures: List[str] = []
    workflows = read_workflows(root)
    failures += check_publish_workflow_exists(workflows)
    publish_text = workflows.get(PUBLISH_FILE)
    if publish_text is not None:
        failures += check_publish_uses_action(publish_text)
        failures += check_no_skip_existing(publish_text)
    failures += check_single_publisher(read_upload_files(root, workflows))
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
    failures += check_workflow_ref(env, tag)
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
            fetch=fetch_simple_index if fetch is None else fetch,
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
