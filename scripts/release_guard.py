"""Stop a PyPI release before upload when something is off.

    python scripts/release_guard.py --pr          # offline checks, for pull requests
    python scripts/release_guard.py --tag v0.2.1  # --pr checks plus release checks

Exit code 0 when every check passes. Exit code 1 otherwise, with one line per
failure that says what is wrong and what to do.

Release candidate first: set [project].version to X.Y.Zrc1, tag vX.Y.Zrc1, test
it with pip install --pre, then release X.Y.Z. --tag fails a final whose rc is
not on PyPI, and an rc whose final already is.

The guard catches honest mistakes, not attacks: anyone who can change the
workflows can change this script too, so review of .github/ and scripts/ is
what stops a deliberate change.

The YAML checks search the text instead of parsing it, so the script needs
nothing beyond the standard library, packaging and (below Python 3.11) tomli.
The checks for something forbidden lean toward failing: comments count, and
YAML escapes are decoded and quotes dropped before searching. The check for the
upload step in publish.yml ignores anything after a #. Not caught: a name split
over two lines of a double-quoted string, or an upload that never names the
action, such as twine in a run step.

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
from typing import Any, Callable, Dict, List, Mapping, NamedTuple, Optional, Sequence, Tuple

from packaging.utils import parse_sdist_filename, parse_wheel_filename
from packaging.version import InvalidVersion, Version

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

PACKAGE_NAME = "langchain-brightdata"
REPO_SLUG = f"luminati-io/{PACKAGE_NAME}"
# The Simple API lists every version and file; the JSON API's "releases" key is deprecated.
PYPI_SIMPLE_URL = f"https://pypi.org/simple/{PACKAGE_NAME}/"
PYPI_SIMPLE_JSON = "application/vnd.pypi.simple.v1+json"
WORKFLOWS_DIR = ".github/workflows"
PUBLISH_FILE = "publish.yml"
PUBLISH_PATH = f"{WORKFLOWS_DIR}/{PUBLISH_FILE}"
PUBLISH_ACTION = "pypa/gh-action-pypi-publish"
# Searched for without the owner, so a fork or a copy of the action counts too.
PUBLISH_ACTION_NAME = "gh-action-pypi-publish"
YAML_SUFFIXES = (".yml", ".yaml")
# Build output folders at the top of the repository, never scanned.
BUILD_DIRS = ("build", "dist")
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
# The YAML escapes that can spell a name: \xNN, \uNNNN, \UNNNNNNNN and \/.
_ESCAPE = re.compile(r"\\x([0-9A-Fa-f]{2})|\\u([0-9A-Fa-f]{4})|\\U([0-9A-Fa-f]{8})|\\/")
# Matched case-insensitively, as GitHub matches action names and input names.
_ACTION_MENTION = re.compile(re.escape(PUBLISH_ACTION_NAME), re.IGNORECASE)
_USES_ACTION = re.compile(
    r"""\buses\s*:\s*["']?""" + re.escape(PUBLISH_ACTION) + r"""@[^\s"']+""", re.IGNORECASE
)
# The action reads skip-existing and the older skip_existing.
_SKIP_EXISTING = re.compile(r"skip[-_]existing", re.IGNORECASE)

Fetch = Callable[[str], bytes]
GitRunner = Callable[[Sequence[str]], Tuple[int, str]]


class PyPIVersions(NamedTuple):
    """What the PyPI Simple API lists for the package."""

    listed: List[Version]  # every version, yanked or not
    not_yanked: List[Version]  # versions with at least one file that is not yanked


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


def _unescape(match: "re.Match[str]") -> str:
    digits = match.group(1) or match.group(2) or match.group(3)
    if digits is None:
        return "/"
    code = int(digits, 16)
    return chr(code) if code <= 0x10FFFF else match.group(0)


def _plain_lines(text: str) -> List[str]:
    """Lines to search for something forbidden: YAML escapes decoded, quotes dropped.

    Comments stay, so a mention in a comment counts. Line numbers stay right.
    """
    return [
        _ESCAPE.sub(_unescape, line).replace('"', "").replace("'", "")
        for line in text.splitlines()
    ]


def _parse_version(value: Any) -> Optional[Version]:
    if not isinstance(value, str):
        return None
    try:
        return Version(value)
    except InvalidVersion:
        return None


def _file_version(filename: str) -> Optional[Version]:
    """The version in a wheel or sdist file name, or None when the name does not parse."""
    try:
        if filename.endswith(".whl"):
            return parse_wheel_filename(filename)[1]
        return parse_sdist_filename(filename)[1]
    except ValueError:  # InvalidWheelFilename, InvalidSdistFilename and InvalidVersion
        return None


def _is_rc_of(release: Version, final: Version) -> bool:
    """Whether release is an X.Y.ZrcN of final, not a dev or post release of one."""
    return (
        release.pre is not None
        and release.pre[0] == "rc"
        and release.dev is None
        and release.post is None
        and Version(release.base_version) == final
    )


def read_yaml_files(root: Path) -> Dict[str, str]:
    """Return {repo-relative path: text} for every .yml and .yaml file under root.

    Skipped: .git folders, virtual environments (any folder with a pyvenv.cfg)
    and the build output folders build/ and dist/ at the top.
    """
    files = {}
    for folder, dirs, names in os.walk(root):
        here = Path(folder)
        dirs[:] = sorted(
            name
            for name in dirs
            if name != ".git"
            and not (here == root and name in BUILD_DIRS)
            and not (here / name / "pyvenv.cfg").is_file()
        )
        for name in sorted(names):
            if name.lower().endswith(YAML_SUFFIXES):
                files[(here / name).relative_to(root).as_posix()] = _read(here / name)
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


def check_publish_workflow_exists(files: Mapping[str, str]) -> List[str]:
    """publish.yml must exist under exactly that name."""
    if PUBLISH_PATH in files:
        return []
    return [f"{PUBLISH_PATH} not found; the release workflow must have exactly that name"]


def check_publish_uses_action(publish_text: str) -> List[str]:
    """publish.yml must upload with a step that uses the PyPI publish action itself."""
    if any(_USES_ACTION.search(line) for line in _strip_comments(publish_text)):
        return []
    return [f"{PUBLISH_FILE} has no step that uses {PUBLISH_ACTION}@<ref>; "
            f"upload to PyPI from a step in {PUBLISH_FILE}"]


def check_no_skip_existing(publish_text: str) -> List[str]:
    """publish.yml may not mention skip-existing at all, not even as false or in a comment.

    The action treats every value but "false" as on, and YAML can carry a
    value on to the next line ("false" then "true" reads as "false true"), so
    no mention is the only form that is sure to be off. skip_existing and any
    case count too.
    """
    return [
        f"{PUBLISH_FILE} mentions skip-existing (line {number}); "
        "remove it, a duplicate upload must fail"
        for number, line in enumerate(_plain_lines(publish_text), start=1)
        if _SKIP_EXISTING.search(line)
    ]


def check_single_publisher(files: Mapping[str, str]) -> List[str]:
    """No YAML file but publish.yml may mention the PyPI publish action.

    files maps repo-relative paths to text (see read_yaml_files). Any mention
    counts, in a comment or under any owner: a workflow or action that names
    the action may upload, and so may whatever calls it.
    """
    return [
        f"{path} mentions {PUBLISH_ACTION_NAME}; only {PUBLISH_FILE} may upload to PyPI"
        for path, text in sorted(files.items())
        if path != PUBLISH_PATH and any(_ACTION_MENTION.search(x) for x in _plain_lines(text))
    ]


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


def load_pypi_versions(version: str, fetch: Fetch) -> Tuple[Optional[PyPIVersions], List[str]]:
    """Return what PyPI lists for the package, or None and the failure.

    Fails closed when PyPI cannot be read or does not send the expected JSON.
    Versions and file names that do not parse are skipped. A file counts as
    not yanked only when its "yanked" is false. version is the one being
    released, named in the failure.
    """
    try:
        body = fetch(PYPI_SIMPLE_URL)
    except (OSError, http.client.HTTPException) as exc:
        return None, [f"could not reach PyPI to check {version} ({_one_line(exc)}); "
                      "try again when PyPI is reachable"]
    bad_json = [f"PyPI returned bad JSON for {PACKAGE_NAME}; try again later"]
    try:
        page = json.loads(body)
        versions, files = page["versions"], page["files"]
    except (ValueError, KeyError, TypeError):
        return None, bad_json
    if not isinstance(versions, list) or not all(isinstance(v, str) for v in versions):
        return None, bad_json
    if not isinstance(files, list) or not all(
        isinstance(f, dict) and isinstance(f.get("filename"), str) for f in files
    ):
        return None, bad_json
    listed = [v for v in map(_parse_version, versions) if v is not None]
    live = [_file_version(f["filename"]) for f in files if f.get("yanked", False) is False]
    return PyPIVersions(listed, [v for v in live if v is not None]), []


def check_not_on_pypi(version: str, listed: Sequence[Version]) -> List[str]:
    """The version (a valid PEP 440 string) must not be on PyPI yet, yanked or not.

    listed is PyPIVersions.listed. Versions are compared as PEP 440 versions,
    as PyPI does (0.2 equals 0.2.0).
    """
    if Version(version) in listed:
        return [f"{version} is already on PyPI; bump [project].version and tag the new version"]
    return []


def check_release_candidate_first(
    version: str, listed: Sequence[Version], not_yanked: Sequence[Version]
) -> List[str]:
    """A final X.Y.Z needs an rc on PyPI, and an rc is too late once its own final is out.

    pip installs a pre-release only when asked (pip install --pre, or
    ==X.Y.ZrcN), so an rc on PyPI lets a real install be tested before users
    get the final, and an rc uploaded after its final is never installed by
    default. Only an X.Y.ZrcN with a file that is not yanked counts, not a
    dev or post release of one. An rc of X.Y.Z after a newer final (a
    backport) is fine. version is canonical X.Y.Z or X.Y.ZrcN. Versions are
    compared as PEP 440 versions. There is no override, on purpose.
    """
    wanted = Version(version)
    final = Version(wanted.base_version)
    if wanted.pre is not None:
        if final in listed:
            major, minor, micro = final.release
            return [f"{final} is already on PyPI, so pip never installs an rc of it by default; "
                    "set [project].version to the next version's rc "
                    f"(for example {major}.{minor}.{micro + 1}rc1) and tag that"]
        return []
    if any(_is_rc_of(release, final) for release in not_yanked):
        return []
    return [f"{version} has no release candidate on PyPI; set [project].version to "
            f"{version}rc1, tag v{version}rc1, test it with pip install --pre, "
            f"then release {version}"]


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
    """Offline checks of the YAML files and pyproject.toml."""
    failures: List[str] = []
    files = read_yaml_files(root)
    failures += check_publish_workflow_exists(files)
    publish_text = files.get(PUBLISH_PATH)
    if publish_text is not None:
        failures += check_publish_uses_action(publish_text)
        failures += check_no_skip_existing(publish_text)
    failures += check_single_publisher(files)
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
    # check_project_version reports a version that is not canonical X.Y.Z or X.Y.ZrcN.
    releasable = project is not None and not check_project_version(project)
    if isinstance(version, str) and not tag_failures:
        failures += check_tag_matches_version(tag, version)
    if _parse_version(version) is not None:
        pypi, pypi_failures = load_pypi_versions(version, fetch)
        failures += pypi_failures
        if pypi is not None:
            on_pypi = check_not_on_pypi(version, pypi.listed)
            failures += on_pypi
            # A version that is already out needs a bump first, not an rc.
            if releasable and not on_pypi:
                failures += check_release_candidate_first(version, pypi.listed, pypi.not_yanked)
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
