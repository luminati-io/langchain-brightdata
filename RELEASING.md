# Releasing langchain-brightdata

Pushing a `v*` tag on a commit that is on `main` runs `.github/workflows/publish.yml`: the tests (`.github/workflows/ci.yml`), the release guard (`scripts/release_guard.py --tag`) and the build. Only when all three pass does the upload job start, and it waits until the maintainer approves the `pypi` environment. PyPI takes the upload through trusted publishing, so no token is stored anywhere.

Before the very first release, create the `pypi` environment in the repository settings (Settings, Environments) with the maintainer as a required reviewer. If it does not exist, GitHub creates it on the first run with no protection, and the upload waits for no one. Set it up by hand and do not rely on the guard for it: a guard check can stop a release, but it cannot create the environment or add the reviewer.

## Optional: let specific testers try a branch first

Nothing here reaches PyPI. Either:

- build a wheel from the branch and send the `.whl` file privately: `pip install build==1.6.1`, then `python -m build` (the wheel lands in `dist/`), or
- have testers install the branch: `pip install "git+https://github.com/luminati-io/langchain-brightdata@<branch>"`. The repository is public, so anyone can see the branch.

## Release steps

Every release goes out as a release candidate (rc) first. pip installs an rc only when asked, so users keep getting the last final.

1. Open a PR that sets `[project].version` in `pyproject.toml` to `X.Y.Zrc1`. Merge it when `ci-ok` is green.
2. Tag the commit that PR made on `main`, and push the tag:
   ```sh
   git fetch origin
   git tag vX.Y.Zrc1 <sha>
   git push origin vX.Y.Zrc1
   ```
3. In the Actions tab, open the "Publish to PyPI" run. When tests, guard and build have passed, approve the `pypi` environment (Review deployments).
4. In a clean virtual environment, install the rc and check it:
   ```sh
   pip install langchain-brightdata==X.Y.Zrc1
   python -c "from importlib.metadata import version; from langchain_brightdata import BrightDataSERP, BrightDataUnlocker, BrightDataWebScraperAPI; print(version('langchain-brightdata'))"
   ```
   `pip install --pre langchain-brightdata` works too, but takes the newest pre-release, which may not be this one. If pip does not see the new version yet, wait a minute. If the change touches a tool, try one real call with your own key.
5. If the rc is good, open a PR that sets the version to `X.Y.Z`, merge it, tag `vX.Y.Z` on that commit, approve, and check again with `pip install langchain-brightdata==X.Y.Z`. If the rc is not good, fix it on a PR and release `X.Y.Zrc2` the same way.

The guard refuses:

- a final `X.Y.Z` when PyPI has no `X.Y.ZrcN` that is not yanked,
- an rc of `X.Y.Z` once `X.Y.Z` is on PyPI,
- a tag that does not match the committed `[project].version`,
- a version already on PyPI, yanked or not,
- a tagged commit that is not on `main`,
- a run that is not `publish.yml` started by that tag.

## What the guard messages mean

The guard prints one line per failure. Its `--pr` checks (rows 1 to 12) also run on every pull request, in the `guard` job of `ci.yml`. Text in braces is filled in at run time.

| # | Message | What to do |
|---|---|---|
| 1 | `pyproject.toml not found; run the guard on the repository root` | Run it from the repository root. |
| 2 | `pyproject.toml is not valid TOML ({error}); fix the file` | Fix the syntax error it names. |
| 3 | `pyproject.toml has no [project] table; add one with name and version` | Restore the `[project]` table. |
| 4 | `.github/workflows/publish.yml not found; the release workflow must have exactly that name` | Restore the file under that name. PyPI trusts only that file. |
| 5 | `publish.yml has no step that uses pypa/gh-action-pypi-publish@<ref>; upload to PyPI from a step in publish.yml` | Put the upload step back in `publish.yml`, pinned by commit SHA. |
| 6 | `publish.yml mentions skip-existing (line {number}); remove it, a duplicate upload must fail` | Delete that line, even if it is a comment. |
| 7 | `{path} mentions gh-action-pypi-publish; only publish.yml may upload to PyPI` | Remove the mention from that file. |
| 8 | `pyproject name is {name}, expected langchain-brightdata; set [project].name to langchain-brightdata` | Set the name back. |
| 9 | `pyproject has no [project].version string; set a static one like version = "0.2.1"` | Write the version as a plain string. |
| 10 | `pyproject version {version} is not a valid PEP 440 version; use one like 0.2.1` | Fix the version. |
| 11 | `pyproject version {version} is not canonical PEP 440; write it as {canonical}` | Write it as shown. |
| 12 | `pyproject version {version} is not X.Y.Z or X.Y.ZrcN, so no release tag can match it; use a version like 0.2.1` | Use `X.Y.Z` or `X.Y.ZrcN`, no dev, post, a or b. |
| 13 | `tag {tag} is not of the form vX.Y.Z or vX.Y.ZrcN; push a tag like v0.2.1` | Push a correctly named tag. |
| 14 | `tag {tag} does not match pyproject {version}; set [project].version to {tag_version} or tag v{version}` | Tag the committed version, or change the version on a PR first. |
| 15 | `could not reach PyPI to check {version} ({error}); try again when PyPI is reachable` | Re-run all jobs later. |
| 16 | `PyPI returned bad JSON for langchain-brightdata; try again later` | Re-run all jobs later. |
| 17 | `{version} is already on PyPI; bump [project].version and tag the new version` | PyPI never takes a version twice. Bump it on a PR and tag that. |
| 18 | `{X.Y.Z} is already on PyPI, so pip never installs an rc of it by default; set [project].version to the next version's rc (for example {X}.{Y}.{Z+1}rc1) and tag that` | Release an rc of the next version. |
| 19 | `{version} has no release candidate on PyPI; set [project].version to {version}rc1, tag v{version}rc1, test it with pip install --pre, then release {version}` | Release `X.Y.Zrc1` first (steps 1 to 4). A yanked rc does not count. |
| 20 | `GITHUB_WORKFLOW_REF is not set; run --tag only inside the publish workflow on GitHub Actions` | Locally, use `--pr`. |
| 21 | `workflow ref {ref} is not {expected}; release only from publish.yml, started by pushing tag {tag}` | Release only by pushing a tag to this repository. |
| 22 | `origin/main is not available; check out with fetch-depth: 0 so the guard can see main` | Restore `fetch-depth: 0` in the guard job's checkout. |
| 23 | `HEAD is not on main; tag a commit that is already on main` | Merge first, then tag the commit on `main`. |
| 24 | `could not check whether HEAD is on main (git exit {code}: {output}); check that the checkout is a full git clone` | Check the guard job's checkout step, then re-run all jobs. |

## Rollback

- Never delete or reuse a version: PyPI refuses a file name it has seen before, forever. Never move or delete a published tag.
- Preferred: revert the bad change on `main` with a PR, then release `X.Y.(Z+1)` through an rc, as above.
- Yank only when the bad version breaks installs. A yanked version is skipped by `pip install langchain-brightdata`, but an exact pin such as `==X.Y.Z` still installs it. Only a PyPI project Owner can yank.
- A yanked version still counts as on PyPI, and a yanked rc no longer counts as the rc for its final.

## If a release run fails

| Job | What failed | What to do |
|---|---|---|
| tests | lint, tests or `--pr` guard from `ci.yml`, on the tagged commit | Fix it on a PR, then release the next unused version. |
| guard | a release check | Read the message, see the table above. |
| build | `dist/` did not hold exactly the wheel and sdist for the tag, or the wheel did not install and import | Fix it on a PR, then release the next unused version. |
| publish | the approval was rejected, or the upload failed: usually trusted publishing (OIDC) or the `pypi` environment | Check that PyPI's trusted publisher names this repository, `publish.yml` and, if set, the `pypi` environment. Then re-run all jobs. |

"Next unused version" means a version with no tag yet: the next rc, or `X.Y.(Z+1)rc1` when `vX.Y.Z` is already tagged. Do not move the old tag.

To re-run, always use "Re-run all jobs", never "Re-run failed jobs". Re-running only the failed job reuses the guard result and the build artifact of the earlier run (the artifact is kept 7 days, then the download fails), so the guard's PyPI checks do not run again.

Re-running all jobs is safe: the upload step does not skip files that already exist, so a duplicate upload fails instead of being skipped, and the guard refuses a version that is already on PyPI.
