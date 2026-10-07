"""Tests for scripts/release_guard.py: one failing case per rule, plus all-pass cases.

Offline: PyPI and git are fakes, except one test that runs git in tmp_path.
"""

import functools
import importlib.util
import json
import shutil
import subprocess
import urllib.error
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "release_guard", REPO_ROOT / "scripts" / "release_guard.py"
)
assert _spec is not None and _spec.loader is not None
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

# Release list from https://pypi.org/pypi/langchain-brightdata/json, taken by hand on 2026-10-07.
PYPI_RELEASES_2026_10_07 = [
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

GOOD_REF = "luminati-io/langchain-brightdata/.github/workflows/publish.yml@refs/tags/v0.2.1"
GOOD_ENV = {"GITHUB_WORKFLOW_REF": GOOD_REF}

ORIGIN_MAIN = ("rev-parse", "--verify", "--quiet", "refs/remotes/origin/main^{commit}")
IS_ANCESTOR = ("merge-base", "--is-ancestor", "HEAD", "refs/remotes/origin/main")

SKIP_EXISTING_LINE = len(PUBLISH_YML.splitlines()) + 2
ORIGIN_MAIN_MISSING = (
    "origin/main is not available; check out with fetch-depth: 0 so the guard can see main"
)
NOT_ON_MAIN = "HEAD is not on main; tag a commit that is already on main"


def make_repo(
    root: Path,
    *,
    name: str = "langchain-brightdata",
    version: str = "0.2.1",
    publish: Optional[str] = PUBLISH_YML,
    others: Optional[Dict[str, str]] = None,
) -> Path:
    """Write a minimal pyproject.toml and .github/workflows tree under root."""
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\nversion = "{version}"\n', encoding="utf-8"
    )
    workflows = root / ".github" / "workflows"
    workflows.mkdir(parents=True)
    files = dict(others or {})
    if publish is not None:
        files["publish.yml"] = publish
    for file_name, text in files.items():
        (workflows / file_name).write_text(text, encoding="utf-8")
    return root


def pypi(releases: Sequence[str]) -> Callable[[str], bytes]:
    """A fake PyPI JSON endpoint with these releases."""

    def fetch(url: str) -> bytes:
        assert url == "https://pypi.org/pypi/langchain-brightdata/json"
        return json.dumps({"releases": {version: [] for version in releases}}).encode()

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
    fetch: Callable[[str], bytes] = pypi(PYPI_RELEASES_2026_10_07),
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
        fetch=pypi(PYPI_RELEASES_2026_10_07),
        git=GIT_ON_MAIN,
    )
    assert code == 0
    assert capsys.readouterr().out == "All checks passed for v0.2.1.\n"


def test_tag_rc_all_pass(tmp_path: Path) -> None:
    make_repo(tmp_path, version="0.2.1rc1")
    assert tag_failures(tmp_path, tag="v0.2.1rc1") == []


# --pr rules


def test_publish_yml_missing(tmp_path: Path) -> None:
    make_repo(tmp_path, publish=None)
    assert guard.pr_checks(tmp_path) == [
        ".github/workflows/publish.yml not found; the release workflow must have exactly that name"
    ]


def test_publish_yml_needs_exact_name(tmp_path: Path) -> None:
    make_repo(tmp_path, publish=None, others={"Publish.yml": PUBLISH_YML})
    assert guard.pr_checks(tmp_path) == [
        ".github/workflows/publish.yml not found; the release workflow must have exactly that name",
        "Publish.yml also uses pypa/gh-action-pypi-publish; only publish.yml may upload to PyPI",
    ]


def test_publish_yml_without_action_step(tmp_path: Path) -> None:
    publish = PUBLISH_YML.replace(
        "uses: pypa/gh-action-pypi-publish@release/v1", "run: twine upload dist/*"
    )
    make_repo(tmp_path, publish=publish)
    assert guard.pr_checks(tmp_path) == [
        "publish.yml has no step that uses pypa/gh-action-pypi-publish@<ref>; "
        "upload to PyPI from a step in publish.yml"
    ]


def test_other_workflow_uses_action(tmp_path: Path) -> None:
    release = "jobs:\n  up:\n    steps:\n      - uses: pypa/gh-action-pypi-publish@v1.12.4\n"
    make_repo(tmp_path, others={"release.yaml": release})
    assert guard.pr_checks(tmp_path) == [
        "release.yaml also uses pypa/gh-action-pypi-publish; only publish.yml may upload to PyPI"
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
        "nightly.yml calls publish.yml, which uploads to PyPI; only publish.yml may upload to PyPI",
        "release.yml calls upload.yml, which uploads to PyPI; only publish.yml may upload to PyPI",
        "upload.yml also uses pypa/gh-action-pypi-publish; only publish.yml may upload to PyPI",
    ]


def test_action_in_a_comment_is_not_a_use(tmp_path: Path) -> None:
    ci = "jobs:\n  lint:\n    steps:\n      # - uses: pypa/gh-action-pypi-publish@release/v1\n"
    make_repo(tmp_path, others={"ci.yml": ci})
    assert guard.pr_checks(tmp_path) == []


@pytest.mark.parametrize(
    "line, key",
    [
        ("skip-existing: true", "skip-existing"),
        ("skip_existing: true", "skip_existing"),
        ("Skip-Existing: 'yes'", "Skip-Existing"),
        ("skip-existing: ${{ inputs.skip }}", "skip-existing"),
        ("skip-existing:", "skip-existing"),
    ],
)
def test_skip_existing_fails(tmp_path: Path, line: str, key: str) -> None:
    make_repo(tmp_path, publish=PUBLISH_YML + f"        with:\n          {line}\n")
    assert guard.pr_checks(tmp_path) == [
        f"publish.yml line {SKIP_EXISTING_LINE} sets {key}; "
        "remove it so uploading a version that is already on PyPI fails"
    ]


@pytest.mark.parametrize("value", ["false", "False", '"false"', "false  # explicit"])
def test_skip_existing_false_passes(tmp_path: Path, value: str) -> None:
    make_repo(tmp_path, publish=PUBLISH_YML + f"        with:\n          skip-existing: {value}\n")
    assert guard.pr_checks(tmp_path) == []


def test_pyproject_missing(tmp_path: Path) -> None:
    make_repo(tmp_path)
    (tmp_path / "pyproject.toml").unlink()
    assert guard.pr_checks(tmp_path) == [
        "pyproject.toml not found; run the guard on the repository root"
    ]


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


# --tag rules


@pytest.mark.parametrize("tag", ["v0.2", "0.2.1", "v0.2.1-rc1"])
def test_bad_tag_format(tmp_path: Path, tag: str) -> None:
    make_repo(tmp_path)
    assert tag_failures(tmp_path, tag=tag) == [
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
    assert tag_failures(tmp_path, tag="v0.2.0") == [
        "0.2.0 is already on PyPI; bump [project].version and tag the new version"
    ]


def test_pypi_unreachable_fails_closed(tmp_path: Path) -> None:
    def unreachable(url: str) -> bytes:
        raise urllib.error.URLError("network is down")

    make_repo(tmp_path)
    assert tag_failures(tmp_path, fetch=unreachable) == [
        "could not reach PyPI to check 0.2.1 (<urlopen error network is down>); "
        "try again when PyPI is reachable"
    ]


@pytest.mark.parametrize("body", [b"<html>busy</html>", b'{"info": {}}', b'{"releases": []}'])
def test_pypi_bad_json_fails_closed(tmp_path: Path, body: bytes) -> None:
    make_repo(tmp_path)
    assert tag_failures(tmp_path, fetch=lambda url: body) == [
        "PyPI returned bad JSON for langchain-brightdata; try again later"
    ]


def test_workflow_ref_is_not_publish_yml(tmp_path: Path) -> None:
    ref = "luminati-io/langchain-brightdata/.github/workflows/release.yml@refs/tags/v0.2.1"
    make_repo(tmp_path)
    assert tag_failures(tmp_path, env={"GITHUB_WORKFLOW_REF": ref}) == [
        f"workflow ref {ref} is not publish.yml in luminati-io/langchain-brightdata; "
        "release only from .github/workflows/publish.yml"
    ]


def test_workflow_ref_missing(tmp_path: Path) -> None:
    make_repo(tmp_path)
    assert tag_failures(tmp_path, env={}) == [
        "GITHUB_WORKFLOW_REF is not set; "
        "run --tag only inside the publish workflow on GitHub Actions"
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
    # Keep this machine's git config (signing, hooks, templates) out of the throwaway repo.
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
        "publish.yml line 39 sets skip-existing; "
        "remove it so uploading a version that is already on PyPI fails"
    ]
