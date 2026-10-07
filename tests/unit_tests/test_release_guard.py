"""Tests for scripts/release_guard.py: one failing case per rule, plus all-pass cases.

Offline: PyPI, the GitHub API and git are fakes, except one test that runs git in tmp_path.
"""

import email.message
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
# PyPI once v0.2.1rc1 is out, so a final v0.2.1 may release: the default for --tag tests.
PYPI_WITH_RC1 = [*PYPI_VERSIONS_2026_10_07, "0.2.1rc1"]

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
MENTIONS_ACTION = f"mentions gh-action-pypi-publish; {ONLY_PUBLISH}"
ORIGIN_MAIN_MISSING = (
    "origin/main is not available; check out with fetch-depth: 0 so the guard can see main"
)
NOT_ON_MAIN = "HEAD is not on main; tag a commit that is already on main"
BAD_JSON = "PyPI returned bad JSON for langchain-brightdata; try again later"


def skip_existing_at(line: int) -> str:
    return (
        f"publish.yml mentions skip-existing (line {line}); "
        "remove it, a duplicate upload must fail"
    )


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


def wheel_and_sdist(version: str) -> List[str]:
    """The file names PyPI shows for one upload of version."""
    stem = f"langchain_brightdata-{version}"
    return [f"{stem}-py3-none-any.whl", f"{stem}.tar.gz"]


def pypi(
    versions: Sequence[str], yanked: Sequence[str] = (), files: Optional[Sequence[str]] = None
) -> Callable[[str], bytes]:
    """A fake PyPI Simple API JSON page that lists these versions, shaped like the real one.

    files are the file names, by default a wheel and an sdist for each version.
    The files named in yanked are yanked.
    """
    names = [n for v in versions for n in wheel_and_sdist(v)] if files is None else files

    def fetch(url: str) -> bytes:
        assert url == "https://pypi.org/simple/langchain-brightdata/"
        page = {
            "meta": {"api-version": "1.4"},
            "name": "langchain-brightdata",
            "versions": list(versions),
            "files": [
                {
                    "filename": name,
                    "url": f"https://files.pythonhosted.org/packages/{name}",
                    "hashes": {"sha256": "0" * 64},
                    "yanked": "broken build" if name in yanked else False,
                }
                for name in names
            ],
        }
        return json.dumps(page).encode()

    return fetch


def fake_git(results: Dict[Tuple[str, ...], Tuple[int, str]]) -> Callable:
    """A git runner that answers only the exact commands in results."""

    def git(args: Sequence[str]) -> Tuple[int, str]:
        return results[tuple(args)]

    return git


GIT_ON_MAIN = fake_git({ORIGIN_MAIN: (0, "abc123"), IS_ANCESTOR: (0, "")})

ENVIRONMENT_URL = "https://api.github.com/repos/luminati-io/langchain-brightdata/environments/pypi"
ENVIRONMENT_FIX = (
    "in repository settings create it with a required reviewer, admins unable to bypass, "
    "and deployments limited to v* tags"
)


def unprotected(reasons: str) -> str:
    return f"the pypi environment is missing or unprotected ({reasons}); {ENVIRONMENT_FIX}"


def protected_environment() -> Dict[str, Any]:
    """A GitHub "Get an environment" reply for a protected pypi environment.

    Shaped like the real reply for pypa/pip's protected PyPI environment, read on 2026-10-07:
    the REST docs leave can_admins_bypass out, but the API sends it.
    """
    return {
        "id": 1,
        "node_id": "EN_1",
        "name": "pypi",
        "url": ENVIRONMENT_URL,
        "html_url": "https://github.com/luminati-io/langchain-brightdata/deployments/activity_log",
        "created_at": "2026-10-07T00:00:00Z",
        "updated_at": "2026-10-07T00:00:00Z",
        "can_admins_bypass": False,
        "protection_rules": [
            {"id": 1, "node_id": "GA_1", "type": "branch_policy"},
            {
                "id": 2,
                "node_id": "GA_2",
                "type": "required_reviewers",
                "prevent_self_review": False,
                "reviewers": [{"type": "User", "reviewer": {"login": "maintainer", "id": 1}}],
            },
        ],
        "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True},
    }


def github(page: Any) -> Callable[[str], bytes]:
    """A fake GitHub API that answers the pypi environment URL with page as JSON."""

    def fetch(url: str) -> bytes:
        assert url == ENVIRONMENT_URL
        return json.dumps(page).encode()

    return fetch


def github_error(error: Exception) -> Callable[[str], bytes]:
    def fetch(url: str) -> bytes:
        raise error

    return fetch


def http_error(code: int, reason: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(ENVIRONMENT_URL, code, reason, email.message.Message(), None)


PROTECTED = github(protected_environment())


def tag_failures(
    root: Path,
    tag: str = "v0.2.1",
    env: Optional[Dict[str, str]] = None,
    fetch: Callable[[str], bytes] = pypi(PYPI_WITH_RC1),
    git: Callable = GIT_ON_MAIN,
    environment: Callable[[str], bytes] = PROTECTED,
) -> List[str]:
    return guard.tag_checks(
        root,
        tag,
        env=GOOD_ENV if env is None else env,
        fetch=fetch,
        git=git,
        fetch_environment=environment,
    )


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
        fetch=pypi(PYPI_WITH_RC1),
        git=GIT_ON_MAIN,
        fetch_environment=PROTECTED,
    )
    assert code == 0
    assert capsys.readouterr().out == "All checks passed for v0.2.1.\n"


def test_tag_rc_all_pass(tmp_path: Path) -> None:
    make_repo(tmp_path, version="0.2.1rc1")
    env = {"GITHUB_WORKFLOW_REF": GOOD_REF.replace("v0.2.1", "v0.2.1rc1")}
    fetch = pypi(PYPI_VERSIONS_2026_10_07)
    assert tag_failures(tmp_path, tag="v0.2.1rc1", env=env, fetch=fetch) == []


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
        f".github/workflows/Publish.yml {MENTIONS_ACTION}",
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
        "- uses: someone/gh-action-pypi-publish@v1",
        '- {name: "a #b", uses: pypa/gh-action-pypi-publish@v1}',
        "# - uses: pypa/gh-action-pypi-publish@release/v1",
        '- uses: "pypa\\/gh-action-pypi-publish@release/v1"',
        '- uses: "pypa/gh-action-pypi\\x2dpublish@v1"',
        '- uses: "pypa/gh-action-pypi\\u002Dpublish@v1"',
        '- uses: "pypa/gh-action-pypi\\U0000002dpublish@v1"',
        "- run: docker run \"ghcr.io/pypa/gh-action-\"'pypi-publish:release-v1'",
    ],
)
def test_other_workflow_mentions_action(tmp_path: Path, step: str) -> None:
    make_repo(tmp_path, others={"release.yaml": f"jobs:\n  up:\n    steps:\n      {step}\n"})
    assert guard.pr_checks(tmp_path) == [f".github/workflows/release.yaml {MENTIONS_ACTION}"]


def test_reusable_workflow_that_uploads_fails(tmp_path: Path) -> None:
    upload = (
        "on: workflow_call\njobs:\n  up:\n    steps:\n"
        "      - uses: pypa/gh-action-pypi-publish@v1\n"
    )
    release = "jobs:\n  release:\n    uses: ./.github/workflows/upload.yml\n"
    make_repo(tmp_path, others={"upload.yml": upload, "release.yml": release})
    # The caller does not name the action; the file that does is the one to fix.
    assert guard.pr_checks(tmp_path) == [f".github/workflows/upload.yml {MENTIONS_ACTION}"]


# However a workflow calls an upload action, the action file itself fails.
@pytest.mark.parametrize(
    "action, step",
    [
        ("tools/up/action.yml", "- uses: ./tools/up"),
        ("tools/up/action.yml", '- "uses": ./tools/up'),
        ("tools/up/action.yml", "- uses: >-\n          ./tools/up"),
        ("tools/up/action.yml", "- uses:\n          ./tools/up"),
        ("tools/up/action.yml", "- uses: *up"),
        ("tools/up/action.yml", '- uses: "./tools\\/up"'),
        ("tools/my up/action.yaml", '- uses: "./tools/my up"'),
        (".github/actions/a/b/action.yml", "- uses: ./.github/actions/a"),
    ],
)
def test_upload_action_fails_however_it_is_called(tmp_path: Path, action: str, step: str) -> None:
    release = f"env:\n  UP: &up ./tools/up\njobs:\n  up:\n    steps:\n      {step}\n"
    make_repo(
        tmp_path,
        others={"release.yml": release},
        files={
            action: UPLOAD_STEP,
            ".github/actions/a/action.yml": "runs:\n  steps:\n    - uses: ./.github/actions/a/b\n",
        },
    )
    assert guard.pr_checks(tmp_path) == [f"{action} {MENTIONS_ACTION}"]


def test_uncalled_action_that_uploads_fails(tmp_path: Path) -> None:
    make_repo(tmp_path, files={".github/actions/release/upload/action.yaml": UPLOAD_STEP})
    assert guard.pr_checks(tmp_path) == [
        f".github/actions/release/upload/action.yaml {MENTIONS_ACTION}"
    ]


def test_every_yaml_file_is_scanned(tmp_path: Path) -> None:
    make_repo(
        tmp_path,
        files={
            "tools/build/action.yml": UPLOAD_STEP,  # build/ is skipped only at the top
            "deploy/Release.YML": UPLOAD_STEP,
            "docs/upload.md": UPLOAD_STEP,  # not YAML
        },
    )
    assert guard.pr_checks(tmp_path) == [
        f"deploy/Release.YML {MENTIONS_ACTION}",
        f"tools/build/action.yml {MENTIONS_ACTION}",
    ]


def test_git_build_output_and_virtual_environments_are_skipped(tmp_path: Path) -> None:
    make_repo(
        tmp_path,
        files={
            ".git/hooks/upload.yml": UPLOAD_STEP,
            "vendor/lib/.git/upload.yml": UPLOAD_STEP,
            "build/lib/upload.yml": UPLOAD_STEP,
            "dist/upload.yaml": UPLOAD_STEP,
            ".venv/pyvenv.cfg": "home = /usr/bin\n",
            ".venv/lib/site-packages/pkg/upload.yml": UPLOAD_STEP,
            "tools/env2/pyvenv.cfg": "home = /usr/bin\n",
            "tools/env2/upload.yml": UPLOAD_STEP,
        },
    )
    assert guard.pr_checks(tmp_path) == []


@pytest.mark.parametrize(
    "folder", ["node_modules", ".tox", ".nox", ".venv", "venv", "site-packages", "__pycache__"]
)
def test_tool_folders_are_skipped_at_any_depth(tmp_path: Path, folder: str) -> None:
    # No pyvenv.cfg: the folder name alone is enough.
    make_repo(tmp_path, files={f"tools/{folder}/pkg/upload.yml": UPLOAD_STEP})
    assert guard.pr_checks(tmp_path) == []


DEPENDABOT = """\
version: 2
updates:
  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: weekly
    ignore:
      - dependency-name: pypa/gh-action-pypi-publish
"""


@pytest.mark.parametrize("path", [".github/dependabot.yml", ".github/dependabot.yaml"])
def test_dependabot_config_may_name_the_action(tmp_path: Path, path: str) -> None:
    make_repo(tmp_path, files={path: DEPENDABOT})
    assert guard.pr_checks(tmp_path) == []


@pytest.mark.parametrize(
    "path", ["dependabot.yml", ".github/workflows/dependabot.yml", "tools/.github/dependabot.yml"]
)
def test_only_the_dependabot_config_is_exempt(tmp_path: Path, path: str) -> None:
    make_repo(tmp_path, files={path: DEPENDABOT})
    assert guard.pr_checks(tmp_path) == [f"{path} {MENTIONS_ACTION}"]


# Any mention fails, false and comments too: YAML reads "false" with a next line "true"
# as "false true", and the action treats every value but "false" as on.
@pytest.mark.parametrize(
    "lines",
    [
        "with:\n  skip-existing: true",
        "with:\n  skip_existing: true",
        "with:\n  Skip-Existing: 'yes'",
        "with:\n  skip-existing: ${{ inputs.skip }}",
        "with:\n  skip-existing:",
        "with:\n  skip-existing: false",
        "with:\n  Skip-Existing: False",
        "with:\n  skip-existing: false\n    true",
        "with:\n  ? skip-existing\n  : true",
        "with:\n  # skip-existing: true",
        'with:\n  "skip\\x2dexisting": true',
        'with:\n  "skip\\u002Dexisting": true',
        'with:\n  "skip\\U0000005Fexisting": true',
        'with: {print-hash: "a #b", skip-existing: true}',
    ],
)
def test_skip_existing_mentioned_fails(tmp_path: Path, lines: str) -> None:
    suffix = "".join(f"        {line}\n" for line in lines.splitlines())
    make_repo(tmp_path, publish=PUBLISH_YML + suffix)
    # The line that names it is the one after "with:", or "with:" itself.
    number = PUBLISH_LINES + (1 if lines.startswith("with: {") else 2)
    assert guard.pr_checks(tmp_path) == [skip_existing_at(number)]


def test_each_skip_existing_line_is_named(tmp_path: Path) -> None:
    with_false = "        with:\n          skip-existing: false\n"
    make_repo(tmp_path, publish="# skip_existing stays off\n" + PUBLISH_YML + with_false)
    assert guard.pr_checks(tmp_path) == [skip_existing_at(1), skip_existing_at(PUBLISH_LINES + 3)]


def test_escape_beyond_unicode_is_kept(tmp_path: Path) -> None:
    make_repo(tmp_path, publish=PUBLISH_YML + '        env:\n          NOTE: "\\UFFFFFFFF"\n')
    assert guard.pr_checks(tmp_path) == []


def test_tag_runs_the_pr_checks(tmp_path: Path) -> None:
    make_repo(tmp_path, publish=PUBLISH_YML + "        with:\n          skip-existing: true\n")
    assert tag_failures(tmp_path) == [skip_existing_at(PUBLISH_LINES + 2)]


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
    # 0.2.0 has no rc on PyPI either, but a version that is out needs a bump, not an rc.
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
        b'{"versions": []}',
        b'{"versions": "0.2.1", "files": []}',
        b'{"versions": [1], "files": []}',
        b'{"versions": [], "files": {}}',
        b'{"versions": [], "files": [1]}',
        b'{"versions": [], "files": [{"url": "x"}]}',
        b'{"versions": [], "files": [{"filename": 1}]}',
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


# --tag rules: the pypi environment


def without(key: str) -> Dict[str, Any]:
    page = protected_environment()
    del page[key]
    return page


def with_changes(**changes: Any) -> Dict[str, Any]:
    return {**protected_environment(), **changes}


def reviewers_rule(**changes: Any) -> Dict[str, Any]:
    rule = protected_environment()["protection_rules"][1]
    return {**rule, **changes}


BRANCH_RULE = {"id": 1, "node_id": "GA_1", "type": "branch_policy"}
NO_REVIEWER = "no required reviewer"


@pytest.mark.parametrize(
    "page, reasons",
    [
        (with_changes(protection_rules=[BRANCH_RULE]), NO_REVIEWER),
        (with_changes(protection_rules=[]), NO_REVIEWER),
        (without("protection_rules"), NO_REVIEWER),
        (with_changes(protection_rules=["required_reviewers"]), NO_REVIEWER),
        (with_changes(protection_rules=[reviewers_rule(reviewers=[])]), NO_REVIEWER),
        (with_changes(protection_rules=[reviewers_rule(reviewers=None)]), NO_REVIEWER),
        (with_changes(protection_rules=[reviewers_rule(type="wait_timer")]), NO_REVIEWER),
        (with_changes(can_admins_bypass=True), "admins can bypass"),
        (without("can_admins_bypass"), "admins can bypass"),
        (with_changes(deployment_branch_policy=None), "any branch or tag can deploy"),
        (without("deployment_branch_policy"), "any branch or tag can deploy"),
        (
            with_changes(
                protection_rules=[], can_admins_bypass=True, deployment_branch_policy=None
            ),
            "no required reviewer, admins can bypass, any branch or tag can deploy",
        ),
    ],
)
def test_environment_unprotected(tmp_path: Path, page: Dict[str, Any], reasons: str) -> None:
    make_repo(tmp_path)
    assert tag_failures(tmp_path, environment=github(page)) == [unprotected(reasons)]


def test_environment_only_one_reviewer_rule_needs_reviewers(tmp_path: Path) -> None:
    rules = [reviewers_rule(reviewers=[]), BRANCH_RULE, reviewers_rule()]
    make_repo(tmp_path)
    assert tag_failures(tmp_path, environment=github(with_changes(protection_rules=rules))) == []


def test_environment_not_found(tmp_path: Path) -> None:
    make_repo(tmp_path)
    environment = github_error(http_error(404, "Not Found"))
    assert tag_failures(tmp_path, environment=environment) == [unprotected("not found")]


@pytest.mark.parametrize(
    "code, reason", [(403, "rate limit exceeded"), (429, "Too Many Requests"), (502, "")]
)
def test_environment_http_error_fails_closed(tmp_path: Path, code: int, reason: str) -> None:
    make_repo(tmp_path)
    assert tag_failures(tmp_path, environment=github_error(http_error(code, reason))) == [
        f"could not read the pypi environment from GitHub (HTTP {code}); try again later"
    ]


@pytest.mark.parametrize(
    "error, shown",
    [
        (urllib.error.URLError("network is down"), "<urlopen error network is down>"),
        (TimeoutError("timed out"), "timed out"),
        (http.client.IncompleteRead(b"partial"), "IncompleteRead(7 bytes read)"),
    ],
)
def test_environment_unreachable_fails_closed(
    tmp_path: Path, error: Exception, shown: str
) -> None:
    make_repo(tmp_path)
    assert tag_failures(tmp_path, environment=github_error(error)) == [
        f"could not read the pypi environment from GitHub ({shown}); "
        "try again when GitHub is reachable"
    ]


@pytest.mark.parametrize("body", [b"<html>busy</html>", b"\xff", b"[]", b"null", b'"pypi"'])
def test_environment_bad_json_fails_closed(tmp_path: Path, body: bytes) -> None:
    make_repo(tmp_path)
    assert tag_failures(tmp_path, environment=lambda url: body) == [
        "GitHub returned bad JSON for the pypi environment; try again later"
    ]


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


@pytest.mark.parametrize("token, sent", [("t0ken", "Bearer t0ken"), ("", None), (None, None)])
def test_github_fetch_headers(
    monkeypatch: pytest.MonkeyPatch, token: Optional[str], sent: Optional[str]
) -> None:
    seen = {}

    def urlopen(request: Any, timeout: float) -> FakeResponse:
        seen.update(
            url=request.full_url,
            accept=request.get_header("Accept"),
            version=request.get_header("X-github-api-version"),
            authorization=request.get_header("Authorization"),
            timeout=timeout,
        )
        return FakeResponse(b"{}")

    monkeypatch.setattr(guard.urllib.request, "urlopen", urlopen)
    assert guard.fetch_github_json(ENVIRONMENT_URL, token) == b"{}"
    assert seen == {
        "url": ENVIRONMENT_URL,
        "accept": "application/vnd.github+json",
        "version": "2022-11-28",
        "authorization": sent,
        "timeout": 15.0,
    }


@pytest.mark.parametrize(
    "reply, code", [(json.dumps(protected_environment()).encode(), 0), (None, 1)]
)
def test_main_reads_the_environment_with_github_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    reply: Optional[bytes],
    code: int,
) -> None:
    secret = "ghs_secret_value_123"
    seen = []

    def urlopen(request: Any, timeout: float) -> FakeResponse:
        seen.append((request.full_url, request.get_header("Authorization")))
        if reply is None:
            raise http_error(404, "Not Found")
        return FakeResponse(reply)

    monkeypatch.setattr(guard.urllib.request, "urlopen", urlopen)
    make_repo(tmp_path)
    env = {**GOOD_ENV, "GITHUB_TOKEN": secret}
    args = ["--tag", "v0.2.1", "--root", str(tmp_path)]
    assert guard.main(args, env=env, fetch=pypi(PYPI_WITH_RC1), git=GIT_ON_MAIN) == code
    assert seen == [(ENVIRONMENT_URL, f"Bearer {secret}")]
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err
    if code:
        assert captured.err.splitlines() == [unprotected("not found")]


# --tag rules: release candidate first


def rc_failures(
    tmp_path: Path,
    version: str,
    listed: Sequence[str],
    yanked: Sequence[str] = (),
    files: Optional[Sequence[str]] = None,
) -> List[str]:
    """--tag failures for releasing version when PyPI lists today's versions plus listed."""
    make_repo(tmp_path, version=version)
    env = {"GITHUB_WORKFLOW_REF": GOOD_REF.replace("v0.2.1", f"v{version}")}
    fetch = pypi([*PYPI_VERSIONS_2026_10_07, *listed], yanked=yanked, files=files)
    return tag_failures(tmp_path, tag=f"v{version}", env=env, fetch=fetch)


def no_rc(version: str, rc: int = 1) -> str:
    return (
        f"{version} has no release candidate on PyPI; set [project].version to {version}rc{rc}, "
        f"tag v{version}rc{rc}, test it with pip install --pre, then release {version}"
    )


def test_final_without_rc_on_pypi_fails(tmp_path: Path) -> None:
    assert rc_failures(tmp_path, "0.2.1", []) == [
        "0.2.1 has no release candidate on PyPI; set [project].version to 0.2.1rc1, "
        "tag v0.2.1rc1, test it with pip install --pre, then release 0.2.1"
    ]


def test_rc_of_another_version_does_not_count(tmp_path: Path) -> None:
    assert rc_failures(tmp_path, "0.3.0", ["0.2.1rc1"]) == [
        "0.3.0 has no release candidate on PyPI; set [project].version to 0.3.0rc1, "
        "tag v0.3.0rc1, test it with pip install --pre, then release 0.3.0"
    ]


# Not an rc of 0.2.1: a longer version that starts the same, an older rc, an alpha, a beta,
# a dev build, and a dev or post release of an rc.
@pytest.mark.parametrize(
    "listed",
    [
        "0.2.10rc1", "0.2.0rc1", "0.2.1a1", "0.2.1b1", "0.2.1.dev1", "0.2.1rc1.dev1",
        "0.2.1rc1.post1",
    ],
)
def test_only_an_rc_of_the_same_version_counts(tmp_path: Path, listed: str) -> None:
    assert rc_failures(tmp_path, "0.2.1", [listed]) == [no_rc("0.2.1")]


def test_yanked_rc_does_not_count(tmp_path: Path) -> None:
    # PyPI never takes 0.2.1rc1 again, so the advice is the next free rc.
    yanked = wheel_and_sdist("0.2.1rc1")
    assert rc_failures(tmp_path, "0.2.1", ["0.2.1rc1"], yanked=yanked) == [no_rc("0.2.1", 2)]


# The next free rc is one above the highest rc of the same version, yanked or not.
@pytest.mark.parametrize(
    "listed, yanked, rc",
    [
        (["0.2.1rc1", "0.2.1rc2"], ["0.2.1rc1", "0.2.1rc2"], 3),
        (["0.2.1rc3"], ["0.2.1rc3"], 4),
        (["0.2.1rc2", "0.2.1rc12"], ["0.2.1rc2", "0.2.1rc12"], 13),
        (["0.2.1rc1", "0.3.0rc5"], ["0.2.1rc1"], 2),
        (["0.2.1rc1", "0.2.1rc2.dev1"], ["0.2.1rc1"], 2),
    ],
)
def test_advice_names_the_next_free_rc(
    tmp_path: Path, listed: List[str], yanked: List[str], rc: int
) -> None:
    yanked_files = [name for version in yanked for name in wheel_and_sdist(version)]
    assert rc_failures(tmp_path, "0.2.1", listed, yanked=yanked_files) == [no_rc("0.2.1", rc)]


@pytest.mark.parametrize("yanked", wheel_and_sdist("0.2.1rc1"))
def test_rc_with_one_file_not_yanked_counts(tmp_path: Path, yanked: str) -> None:
    assert rc_failures(tmp_path, "0.2.1", ["0.2.1rc1"], yanked=[yanked]) == []


def test_file_without_a_yanked_key_is_not_yanked(tmp_path: Path) -> None:
    # PEP 691 makes "yanked" optional; leaving it out means the file is not yanked.
    files = [{"filename": "langchain_brightdata-0.2.1rc1.tar.gz"}]
    page = {"versions": [*PYPI_VERSIONS_2026_10_07, "0.2.1rc1"], "files": files}
    make_repo(tmp_path)
    assert tag_failures(tmp_path, fetch=lambda url: json.dumps(page).encode()) == []


def test_file_names_that_do_not_parse_are_skipped(tmp_path: Path) -> None:
    files = [
        "langchain_brightdata-0.2.1rc1.exe",
        "langchain_brightdata-0.2.1rc1-bad.whl",
        "langchain_brightdata-0.2.1rc1x.tar.gz",
        *wheel_and_sdist("0.2.0"),
    ]
    # 0.2.1rc1 is listed, so it is taken even though none of its files counts.
    assert rc_failures(tmp_path, "0.2.1", ["0.2.1rc1"], files=files) == [no_rc("0.2.1", 2)]


# 0.2.1.0rc1 is 0.2.1rc1 under PEP 440, which is how PyPI compares versions.
@pytest.mark.parametrize("listed", ["0.2.1rc1", "0.2.1rc4", "0.2.1.0rc1"])
def test_final_with_its_rc_on_pypi_passes(tmp_path: Path, listed: str) -> None:
    assert rc_failures(tmp_path, "0.2.1", [listed]) == []


@pytest.mark.parametrize("listed", [[], ["0.2.1rc1"]])
def test_rc_passes_with_or_without_an_earlier_rc(tmp_path: Path, listed: List[str]) -> None:
    assert rc_failures(tmp_path, "0.2.1rc2", listed) == []


# A yanked final still blocks: its version can never be uploaded again.
@pytest.mark.parametrize(
    "version, listed, yanked, final, next_rc",
    [
        ("0.2.1rc2", ["0.2.1rc1", "0.2.1"], [], "0.2.1", "0.2.2rc1"),
        ("0.2.1rc1", ["0.2.1"], wheel_and_sdist("0.2.1"), "0.2.1", "0.2.2rc1"),
        ("1.4.9rc1", ["1.4.9"], [], "1.4.9", "1.4.10rc1"),
    ],
)
def test_rc_after_its_final_fails(
    tmp_path: Path, version: str, listed: List[str], yanked: List[str], final: str, next_rc: str
) -> None:
    assert rc_failures(tmp_path, version, listed, yanked=yanked) == [
        f"{final} is already on PyPI, so pip never installs an rc of it by default; "
        f"set [project].version to the next version's rc (for example {next_rc}) and tag that"
    ]


def test_too_late_message_exactly(tmp_path: Path) -> None:
    assert rc_failures(tmp_path, "0.2.1rc1", ["0.2.1"]) == [
        "0.2.1 is already on PyPI, so pip never installs an rc of it by default; "
        "set [project].version to the next version's rc (for example 0.2.2rc1) and tag that"
    ]


def test_backport_rc_passes(tmp_path: Path) -> None:
    # Only the same X.Y.Z final makes an rc too late; a newer final does not.
    assert rc_failures(tmp_path, "0.2.1rc1", ["0.3.0rc1", "0.3.0"]) == []


@pytest.mark.parametrize("version", ["0.2.1.dev1", "0.2.1.post1", "1.0"])
def test_no_rc_advice_for_a_version_no_tag_can_match(tmp_path: Path, version: str) -> None:
    assert rc_failures(tmp_path, version, []) == [
        f"pyproject version {version} is not X.Y.Z or X.Y.ZrcN, so no release tag can match it; "
        "use a version like 0.2.1",
        f"tag v{version} is not of the form vX.Y.Z or vX.Y.ZrcN; push a tag like v0.2.1",
    ]


def test_no_rc_advice_for_a_version_that_is_not_canonical(tmp_path: Path) -> None:
    assert rc_failures(tmp_path, "0.02.1", []) == [
        "pyproject version 0.02.1 is not canonical PEP 440; write it as 0.2.1"
    ]


# The repository itself


def test_repo_passes_pr_checks(capsys: pytest.CaptureFixture) -> None:
    assert guard.main(["--pr"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == "All --pr checks passed.\n"
