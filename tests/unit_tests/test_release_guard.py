"""Tests for scripts/release_guard.py: one failing case per rule, plus all-pass cases.

Offline: PyPI and git are fakes, except one test that runs git in tmp_path.
"""

import functools
import http.client
import importlib.util
import json
import os
import shutil
import subprocess
import urllib.error
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "release_guard", REPO_ROOT / "scripts" / "release_guard.py"
)
assert _spec is not None and _spec.loader is not None
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

# "versions" from the PyPI Simple API (https://pypi.org/simple/langchain-brightdata/ with
# Accept: application/vnd.pypi.simple.v1+json, api-version 1.4), taken by hand on 2026-10-07.
PYPI_VERSIONS_2026_10_07 = [
    "0.1.1", "0.1.2", "0.1.3", "0.1.4", "0.1.5", "0.1.6", "0.1.7", "0.1.8", "0.1.9", "0.2.0",
]

PUBLISH_YML = """\
name: Publish to PyPI

on:
  push:
    tags:
      - "v*"

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      # Upload with the PyPI publish action.
      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
"""
PUBLISH_LINES = len(PUBLISH_YML.splitlines())

UPLOAD_STEP = "runs:\n  using: composite\n  steps:\n    - uses: pypa/gh-action-pypi-publish@v1\n"

GOOD_REF = "luminati-io/langchain-brightdata/.github/workflows/publish.yml@refs/tags/v0.2.1"
GOOD_ENV = {"GITHUB_WORKFLOW_REF": GOOD_REF}

ORIGIN_MAIN = ("rev-parse", "--verify", "--quiet", "refs/remotes/origin/main^{commit}")
IS_ANCESTOR = ("merge-base", "--is-ancestor", "HEAD", "refs/remotes/origin/main")

ONLY_PUBLISH = "only publish.yml may upload to PyPI"
SKIP_EXISTING_FIX = "remove it so uploading a version that is already on PyPI fails"
ORIGIN_MAIN_MISSING = (
    "origin/main is not available; check out with fetch-depth: 0 so the guard can see main"
)
NOT_ON_MAIN = "HEAD is not on main; tag a commit that is already on main"
BAD_JSON = "PyPI returned bad JSON for langchain-brightdata; try again later"


def make_repo(
    root: Path,
    *,
    name: str = "langchain-brightdata",
    version: str = "0.2.1",
    pyproject: Optional[str] = None,
    publish: Optional[str] = PUBLISH_YML,
    others: Optional[Dict[str, str]] = None,
    files: Optional[Dict[str, str]] = None,
) -> Path:
    """Write pyproject.toml, .github/workflows and any other files under root.

    others are extra workflows by file name; files are any other repo-relative paths.
    """
    if pyproject is None:
        pyproject = f'[project]\nname = "{name}"\nversion = "{version}"\n'
    everything = {"pyproject.toml": pyproject}
    if publish is not None:
        everything[".github/workflows/publish.yml"] = publish
    for file_name, text in (others or {}).items():
        everything[f".github/workflows/{file_name}"] = text
    everything.update(files or {})
    for path, text in everything.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text, encoding="utf-8")
    return root


def pypi(versions: Sequence[str]) -> Callable[[str], bytes]:
    """A fake PyPI Simple API JSON page that lists these versions."""

    def fetch(url: str) -> bytes:
        assert url == "https://pypi.org/simple/langchain-brightdata/"
        page = {
            "meta": {"api-version": "1.4"},
            "name": "langchain-brightdata",
            "versions": list(versions),
            "files": [],
        }
        return json.dumps(page).encode()

    return fetch


def fake_git(results: Dict[Tuple[str, ...], Tuple[int, str]]) -> Callable:
    """A git runner that answers only the exact commands in results."""

    def git(args: Sequence[str]) -> Tuple[int, str]:
        return results[tuple(args)]

    return git


GIT_ON_MAIN = fake_git({ORIGIN_MAIN: (0, "abc123"), IS_ANCESTOR: (0, "")})


def tag_failures(
    root: Path,
    tag: str = "v0.2.1",
    env: Optional[Dict[str, str]] = None,
    fetch: Callable[[str], bytes] = pypi(PYPI_VERSIONS_2026_10_07),
    git: Callable = GIT_ON_MAIN,
) -> List[str]:
    return guard.tag_checks(root, tag, env=GOOD_ENV if env is None else env, fetch=fetch, git=git)


# All pass


def test_pr_all_pass(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    make_repo(tmp_path)
    assert guard.main(["--pr", "--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "All --pr checks passed.\n"


def test_tag_all_pass(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    make_repo(tmp_path, version="0.2.1")
    code = guard.main(
        ["--tag", "v0.2.1", "--root", str(tmp_path)],
        env=GOOD_ENV,
        fetch=pypi(PYPI_VERSIONS_2026_10_07),
        git=GIT_ON_MAIN,
    )
    assert code == 0
    assert capsys.readouterr().out == "All checks passed for v0.2.1.\n"


def test_tag_rc_all_pass(tmp_path: Path) -> None:
    make_repo(tmp_path, version="0.2.1rc1")
    env = {"GITHUB_WORKFLOW_REF": GOOD_REF.replace("v0.2.1", "v0.2.1rc1")}
    assert tag_failures(tmp_path, tag="v0.2.1rc1", env=env) == []


def test_default_fetch_asks_the_simple_api_for_json(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def read(self) -> bytes:
            return b"{}"

    def urlopen(request: Any, timeout: float) -> Response:
        seen.update(url=request.full_url, accept=request.get_header("Accept"), timeout=timeout)
        return Response()

    monkeypatch.setattr(guard.urllib.request, "urlopen", urlopen)
    assert guard.fetch_simple_index(guard.PYPI_SIMPLE_URL) == b"{}"
    assert seen == {
        "url": "https://pypi.org/simple/langchain-brightdata/",
        "accept": "application/vnd.pypi.simple.v1+json",
        "timeout": 15.0,
    }


# --pr rules: workflows and actions


def test_publish_yml_missing(tmp_path: Path) -> None:
    make_repo(tmp_path, publish=None)
    assert guard.pr_checks(tmp_path) == [
        ".github/workflows/publish.yml not found; the release workflow must have exactly that name"
    ]


def test_publish_yml_needs_exact_name(tmp_path: Path) -> None:
    make_repo(tmp_path, publish=None, others={"Publish.yml": PUBLISH_YML})
    assert guard.pr_checks(tmp_path) == [
        ".github/workflows/publish.yml not found; the release workflow must have exactly that name",
        f".github/workflows/Publish.yml also uses pypa/gh-action-pypi-publish; {ONLY_PUBLISH}",
    ]


@pytest.mark.parametrize(
    "step",
    [
        "run: twine upload dist/*",
        "# uses: pypa/gh-action-pypi-publish@release/v1",
        "run: twine upload dist/*  # uses: pypa/gh-action-pypi-publish@release/v1",
    ],
)
def test_publish_yml_without_action_step(tmp_path: Path, step: str) -> None:
    publish = PUBLISH_YML.replace("uses: pypa/gh-action-pypi-publish@release/v1", step)
    make_repo(tmp_path, publish=publish)
    assert guard.pr_checks(tmp_path) == [
        "publish.yml has no step that uses pypa/gh-action-pypi-publish@<ref>; "
        "upload to PyPI from a step in publish.yml"
    ]


@pytest.mark.parametrize(
    "step",
    [
        "- uses: pypa/gh-action-pypi-publish@v1.12.4",
        "- uses: PyPA/GH-Action-PyPI-Publish@v1",
        '- {name: "a #b", uses: pypa/gh-action-pypi-publish@v1}',
        '- uses: "pypa/gh-action-pypi\\x2dpublish@v1"',
    ],
)
def test_other_workflow_uses_action(tmp_path: Path, step: str) -> None:
    make_repo(tmp_path, others={"release.yaml": f"jobs:\n  up:\n    steps:\n      {step}\n"})
    assert guard.pr_checks(tmp_path) == [
        f".github/workflows/release.yaml also uses pypa/gh-action-pypi-publish; {ONLY_PUBLISH}"
    ]


def test_other_workflow_uploads_through_reusable_workflow(tmp_path: Path) -> None:
    upload = "jobs:\n  up:\n    steps:\n      - uses: pypa/gh-action-pypi-publish@v1\n"
    release = "jobs:\n  release:\n    uses: ./.github/workflows/upload.yml\n"
    calls_publish = (
        "jobs:\n  release:\n"
        "    uses: luminati-io/langchain-brightdata/.github/workflows/publish.yml@main\n"
    )
    make_repo(
        tmp_path,
        others={"upload.yml": upload, "release.yml": release, "nightly.yml": calls_publish},
    )
    assert guard.pr_checks(tmp_path) == [
        ".github/workflows/nightly.yml calls .github/workflows/publish.yml, "
        f"which uploads to PyPI; {ONLY_PUBLISH}",
        ".github/workflows/release.yml calls .github/workflows/upload.yml, "
        f"which uploads to PyPI; {ONLY_PUBLISH}",
        f".github/workflows/upload.yml also uses pypa/gh-action-pypi-publish; {ONLY_PUBLISH}",
    ]


def test_other_workflow_uploads_through_composite_action(tmp_path: Path) -> None:
    release = "jobs:\n  up:\n    steps:\n      - uses: ./.github/actions/upload\n"
    make_repo(
        tmp_path,
        others={"release.yml": release},
        files={".github/actions/upload/action.yml": UPLOAD_STEP},
    )
    assert guard.pr_checks(tmp_path) == [
        f".github/actions/upload/action.yml also uses pypa/gh-action-pypi-publish; {ONLY_PUBLISH}",
        ".github/workflows/release.yml calls .github/actions/upload/action.yml, "
        f"which uploads to PyPI; {ONLY_PUBLISH}",
    ]


def test_uncalled_action_that_uploads_fails(tmp_path: Path) -> None:
    make_repo(tmp_path, files={".github/actions/release/upload/action.yaml": UPLOAD_STEP})
    assert guard.pr_checks(tmp_path) == [
        ".github/actions/release/upload/action.yaml also uses pypa/gh-action-pypi-publish; "
        f"{ONLY_PUBLISH}"
    ]


def test_actions_outside_github_actions_are_followed(tmp_path: Path) -> None:
    release = "jobs:\n  up:\n    steps:\n      - uses: ./tools/outer/\n"
    outer = "runs:\n  using: composite\n  steps:\n    - uses: ./tools/inner\n"
    make_repo(
        tmp_path,
        others={"release.yml": release},
        files={"tools/outer/action.yml": outer, "tools/inner/action.yaml": UPLOAD_STEP},
    )
    assert guard.pr_checks(tmp_path) == [
        ".github/workflows/release.yml calls tools/outer/action.yml, "
        f"which uploads to PyPI; {ONLY_PUBLISH}",
        f"tools/inner/action.yaml also uses pypa/gh-action-pypi-publish; {ONLY_PUBLISH}",
        "tools/outer/action.yml calls tools/inner/action.yaml, "
        f"which uploads to PyPI; {ONLY_PUBLISH}",
    ]


def test_action_in_a_comment_is_not_a_use(tmp_path: Path) -> None:
    ci = "jobs:\n  lint:\n    steps:\n      # - uses: pypa/gh-action-pypi-publish@release/v1\n"
    make_repo(tmp_path, others={"ci.yml": ci})
    assert guard.pr_checks(tmp_path) == []


@pytest.mark.parametrize(
    "lines, key",
    [
        ("with:\n  skip-existing: true", "skip-existing"),
        ("with:\n  skip_existing: true", "skip_existing"),
        ("with:\n  Skip-Existing: 'yes'", "Skip-Existing"),
        ("with:\n  skip-existing: ${{ inputs.skip }}", "skip-existing"),
        ("with:\n  skip-existing:", "skip-existing"),
        ("with:\n  skip-existing: false#not-a-comment", "skip-existing"),
        ("with:\n  ? skip-existing\n  : true", "skip-existing"),
        ('with:\n  "skip\\x2dexisting": true', "skip-existing"),
        ('with: {print-hash: "a #b", skip-existing: true}', "skip-existing"),
    ],
)
def test_skip_existing_fails(tmp_path: Path, lines: str, key: str) -> None:
    suffix = "".join(f"        {line}\n" for line in lines.splitlines())
    make_repo(tmp_path, publish=PUBLISH_YML + suffix)
    # The first line that names the key is the one after "with:", or "with:" itself.
    number = PUBLISH_LINES + (1 if lines.startswith("with: {") else 2)
    expected = [f"publish.yml line {number} sets {key}; {SKIP_EXISTING_FIX}"]
    assert guard.pr_checks(tmp_path) == expected


@pytest.mark.parametrize(
    "line",
    [
        "skip-existing: false",
        "skip-existing: False",
        'skip-existing: "false"',
        "skip_existing: 'FALSE'",
        "skip-existing: false  # explicit",
        "skip-existing: false   ",
        "# skip-existing: true",
    ],
)
def test_skip_existing_false_passes(tmp_path: Path, line: str) -> None:
    make_repo(tmp_path, publish=PUBLISH_YML + f"        with:\n          {line}\n")
    assert guard.pr_checks(tmp_path) == []


def test_escape_beyond_unicode_is_kept(tmp_path: Path) -> None:
    make_repo(tmp_path, publish=PUBLISH_YML + '        env:\n          NOTE: "\\UFFFFFFFF"\n')
    assert guard.pr_checks(tmp_path) == []


def test_tag_runs_the_pr_checks(tmp_path: Path) -> None:
    make_repo(tmp_path, publish=PUBLISH_YML + "        with:\n          skip-existing: true\n")
    assert tag_failures(tmp_path) == [
        f"publish.yml line {PUBLISH_LINES + 2} sets skip-existing; {SKIP_EXISTING_FIX}"
    ]


# --pr rules: pyproject.toml. Each must also fail --tag.


def test_pyproject_missing(tmp_path: Path) -> None:
    make_repo(tmp_path)
    (tmp_path / "pyproject.toml").unlink()
    expected = ["pyproject.toml not found; run the guard on the repository root"]
    assert guard.pr_checks(tmp_path) == expected
    assert tag_failures(tmp_path) == expected


def test_pyproject_invalid_toml(tmp_path: Path) -> None:
    make_repo(tmp_path, pyproject='[project\nname = "langchain-brightdata"\n')
    for failures in (guard.pr_checks(tmp_path), tag_failures(tmp_path)):
        # The parser's own words differ between tomli and tomllib versions.
        assert len(failures) == 1
        assert failures[0].startswith("pyproject.toml is not valid TOML (")
        assert failures[0].endswith("); fix the file")


def test_pyproject_without_project_table(tmp_path: Path) -> None:
    make_repo(tmp_path, pyproject='[tool.other]\nname = "langchain-brightdata"\n')
    expected = ["pyproject.toml has no [project] table; add one with name and version"]
    assert guard.pr_checks(tmp_path) == expected
    assert tag_failures(tmp_path) == expected


@pytest.mark.parametrize(
    "pyproject",
    [
        '[project]\nname = "langchain-brightdata"\ndynamic = ["version"]\n',
        '[project]\nname = "langchain-brightdata"\nversion = 2\n',
    ],
)
def test_version_missing_or_not_a_string(tmp_path: Path, pyproject: str) -> None:
    make_repo(tmp_path, pyproject=pyproject)
    expected = [
        'pyproject has no [project].version string; set a static one like version = "0.2.1"'
    ]
    assert guard.pr_checks(tmp_path) == expected
    assert tag_failures(tmp_path) == expected


def test_wrong_package_name(tmp_path: Path) -> None:
    make_repo(tmp_path, name="langchain-brightdata2")
    assert guard.pr_checks(tmp_path) == [
        "pyproject name is langchain-brightdata2, expected langchain-brightdata; "
        "set [project].name to langchain-brightdata"
    ]


def test_version_not_canonical(tmp_path: Path) -> None:
    make_repo(tmp_path, version="0.2.01")
    assert guard.pr_checks(tmp_path) == [
        "pyproject version 0.2.01 is not canonical PEP 440; write it as 0.2.1"
    ]


def test_version_not_pep440(tmp_path: Path) -> None:
    make_repo(tmp_path, version="0.2.x")
    assert guard.pr_checks(tmp_path) == [
        "pyproject version 0.2.x is not a valid PEP 440 version; use one like 0.2.1"
    ]


@pytest.mark.parametrize("version", ["0.2.1.dev1", "0.2.1.post1", "0.2.1+local", "0.2.1a1", "1.0"])
def test_version_no_tag_can_match(tmp_path: Path, version: str) -> None:
    make_repo(tmp_path, version=version)
    assert guard.pr_checks(tmp_path) == [
        f"pyproject version {version} is not X.Y.Z or X.Y.ZrcN, so no release tag can match it; "
        "use a version like 0.2.1"
    ]


# --tag rules


@pytest.mark.parametrize("tag", ["v0.2", "0.2.1", "v0.2.1-rc1", "v" + chr(0x660) + ".2.1"])
def test_bad_tag_format(tmp_path: Path, tag: str) -> None:
    make_repo(tmp_path)
    env = {"GITHUB_WORKFLOW_REF": GOOD_REF.replace("v0.2.1", tag)}
    assert tag_failures(tmp_path, tag=tag, env=env) == [
        f"tag {tag} is not of the form vX.Y.Z or vX.Y.ZrcN; push a tag like v0.2.1"
    ]


def test_tag_does_not_match_pyproject(tmp_path: Path) -> None:
    make_repo(tmp_path, version="0.2.0")
    # 0.2.0 is also on PyPI today, so that rule fires as well.
    assert tag_failures(tmp_path, tag="v0.2.1") == [
        "tag v0.2.1 does not match pyproject 0.2.0; set [project].version to 0.2.1 or tag v0.2.0",
        "0.2.0 is already on PyPI; bump [project].version and tag the new version",
    ]


def test_version_already_on_pypi(tmp_path: Path) -> None:
    make_repo(tmp_path, version="0.2.0")
    env = {"GITHUB_WORKFLOW_REF": GOOD_REF.replace("v0.2.1", "v0.2.0")}
    assert tag_failures(tmp_path, tag="v0.2.0", env=env) == [
        "0.2.0 is already on PyPI; bump [project].version and tag the new version"
    ]


def test_pypi_compares_pep440_versions(tmp_path: Path) -> None:
    make_repo(tmp_path, version="0.2.0")
    env = {"GITHUB_WORKFLOW_REF": GOOD_REF.replace("v0.2.1", "v0.2.0")}
    assert tag_failures(tmp_path, tag="v0.2.0", env=env, fetch=pypi(["0.1.9", "0.2"])) == [
        "0.2.0 is already on PyPI; bump [project].version and tag the new version"
    ]


@pytest.mark.parametrize(
    "error, shown",
    [
        (urllib.error.URLError("network is down"), "<urlopen error network is down>"),
        (TimeoutError("timed out"), "timed out"),
        (http.client.IncompleteRead(b"partial"), "IncompleteRead(7 bytes read)"),
    ],
)
def test_pypi_unreachable_fails_closed(tmp_path: Path, error: Exception, shown: str) -> None:
    def unreachable(url: str) -> bytes:
        raise error

    make_repo(tmp_path)
    assert tag_failures(tmp_path, fetch=unreachable) == [
        f"could not reach PyPI to check 0.2.1 ({shown}); try again when PyPI is reachable"
    ]


@pytest.mark.parametrize(
    "body",
    [
        b"<html>busy</html>",
        b"\xff",
        b"[]",
        b'{"name": "langchain-brightdata"}',
        b'{"releases": {"0.2.1": []}}',
        b'{"versions": "0.2.1"}',
        b'{"versions": [1]}',
    ],
)
def test_pypi_bad_json_fails_closed(tmp_path: Path, body: bytes) -> None:
    make_repo(tmp_path)
    assert tag_failures(tmp_path, fetch=lambda url: body) == [BAD_JSON]


def test_workflow_ref_missing(tmp_path: Path) -> None:
    make_repo(tmp_path)
    assert tag_failures(tmp_path, env={}) == [
        "GITHUB_WORKFLOW_REF is not set; "
        "run --tag only inside the publish workflow on GitHub Actions"
    ]


@pytest.mark.parametrize(
    "ref",
    [
        "luminati-io/langchain-brightdata/.github/workflows/release.yml@refs/tags/v0.2.1",
        "luminati-io/langchain-brightdata/.github/workflows/publish.yml@refs/heads/feature",
        "luminati-io/langchain-brightdata/.github/workflows/publish.yml@refs/tags/v0.2.2",
        "someone/langchain-brightdata/.github/workflows/publish.yml@refs/tags/v0.2.1",
        "Luminati-io/langchain-brightdata/.github/workflows/publish.yml@refs/tags/v0.2.1",
    ],
)
def test_workflow_ref_is_not_this_tag_on_publish_yml(tmp_path: Path, ref: str) -> None:
    make_repo(tmp_path)
    assert tag_failures(tmp_path, env={"GITHUB_WORKFLOW_REF": ref}) == [
        f"workflow ref {ref} is not {GOOD_REF}; "
        "release only from publish.yml, started by pushing tag v0.2.1"
    ]


def test_head_not_on_main(tmp_path: Path) -> None:
    make_repo(tmp_path)
    git = fake_git({ORIGIN_MAIN: (0, "abc123"), IS_ANCESTOR: (1, "")})
    assert tag_failures(tmp_path, git=git) == [NOT_ON_MAIN]


def test_origin_main_missing(tmp_path: Path) -> None:
    make_repo(tmp_path)
    assert tag_failures(tmp_path, git=fake_git({ORIGIN_MAIN: (1, "")})) == [ORIGIN_MAIN_MISSING]


def test_git_error(tmp_path: Path) -> None:
    make_repo(tmp_path)
    git = fake_git({ORIGIN_MAIN: (128, "fatal: not a git repository\n(or any parent)")})
    assert tag_failures(tmp_path, git=git) == [
        "could not check whether HEAD is on main "
        "(git exit 128: fatal: not a git repository (or any parent)); "
        "check that the checkout is a full git clone"
    ]


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not on PATH")
def test_head_on_main_with_real_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # git exports GIT_DIR and friends to hooks; any of them would point this test at
    # another repository. Drop them all, and keep this machine's git config out too.
    for variable in list(os.environ):
        if variable.upper().startswith("GIT_"):
            monkeypatch.delenv(variable)
    empty_config = tmp_path / "gitconfig"
    empty_config.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty_config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@example.com")
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    runner = functools.partial(guard.run_git, cwd=repo)
    git("init", "-q")
    git("commit", "-q", "--allow-empty", "-m", "on main")
    assert guard.check_head_on_main(runner) == [ORIGIN_MAIN_MISSING]

    git("update-ref", "refs/remotes/origin/main", "HEAD")
    assert guard.check_head_on_main(runner) == []

    git("checkout", "-q", "-b", "feature")
    git("commit", "-q", "--allow-empty", "-m", "not on main")
    assert guard.check_head_on_main(runner) == [NOT_ON_MAIN]


# The repository itself


def test_repo_fails_only_on_skip_existing(capsys: pytest.CaptureFixture) -> None:
    # Expected today: publish.yml still sets skip-existing. Update this when it is removed.
    assert guard.main(["--pr"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.splitlines() == [
        f"publish.yml line 39 sets skip-existing; {SKIP_EXISTING_FIX}"
    ]
