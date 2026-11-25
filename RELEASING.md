# Releasing langchain-brightdata

Pushing a `v*` tag on a commit that is on `main` runs `.github/workflows/publish.yml`: the tests (`.github/workflows/ci.yml`), the release guard (`scripts/release_guard.py --tag`) and the build. Only when all three pass does the upload job start, and it waits until the maintainer approves the `pypi` environment. PyPI takes the upload through trusted publishing, so no token is stored anywhere. Release runs go one at a time, and runs waiting behind one are all kept, not cancelled (`queue: max`).

## One-time setup

On GitHub, create the `pypi` environment in the repository settings (Settings, Environments) with:

- "Required reviewers": the maintainer.
- "Prevent self-review": off. Otherwise a lone maintainer who pushes the tag cannot approve their own release.
- "Allow administrators to bypass configured protection rules": off.
- "Deployment branches": "Selected branches and tags", then "Add deployment branch or tag rule" with Ref type Tag and pattern `v*`.

Without it, GitHub would create the environment on first use with no protection. The guard reads the environment on every release and refuses when it is missing, has no required reviewer, lets administrators bypass, or lets any branch or tag deploy. It cannot set these for you, and it does not check who the reviewer is, self-review or the `v*` rule.

On PyPI, as a project Owner ("Your projects", "Manage", "Publishing"): add a trusted publisher for `luminati-io/langchain-brightdata`, workflow `publish.yml`, environment `pypi`, then remove the publisher whose environment is Any. An Any publisher lets a tag from a branch with an edited `publish.yml` upload without the approval step. This is safe to do before rc1, because the publish job already uses the `pypi` environment.

## Optional: let specific testers try a branch first

Nothing here reaches PyPI. Either:

- build a wheel from the branch and send the `.whl` file privately: `pip install build==1.6.1`, then `python -m build` (the wheel lands in `dist/`), or
- have testers install the branch: `pip install "git+https://github.com/luminati-io/langchain-brightdata@<branch>"`. The repository is public, so anyone can see the branch.

## Release steps

Every release goes out as a release candidate (rc) first. pip installs an rc only when asked, so users keep getting the last final.

1. Open a PR that sets `[project].version` in `pyproject.toml` to `X.Y.Zrc1`. Merge it when `ci-ok` is green.
2. Find the commit that PR made on `main` (`git log` shows its sha), then tag it and push the tag:
   ```sh
   git fetch origin
   git log -1 origin/main
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
- a run that is not `publish.yml` started by that tag,
- a `pypi` environment that is missing or unprotected.

## What the guard messages mean

The guard prints one line per failure, and most messages say what to do. This table covers the ones that need more. Checks of `pyproject.toml` and the workflow files also run on every pull request (`--pr`, the `guard` job of `ci.yml`). Text in braces is filled in at run time.

| Message | What to do |
|---|---|
| `pyproject.toml not found; run the guard on the repository root` | Restore `pyproject.toml`. |
| `.github/workflows/publish.yml not found; the release workflow must have exactly that name` | Restore the file under that name. PyPI trusts only that file. |
| `publish.yml has no step that uses pypa/gh-action-pypi-publish@<ref>; upload to PyPI from a step in publish.yml` | Put the upload step back in `publish.yml`, pinned by commit SHA. |
| `publish.yml mentions skip-existing (line {number}); remove it, a duplicate upload must fail` | Delete that line, even if it is a comment. |
| `{path} mentions gh-action-pypi-publish; only publish.yml may upload to PyPI` | Remove the mention from that file. `.github/dependabot.yml` is exempt. |
| `tag {tag} does not match pyproject {version}; set [project].version to {tag_version} or tag v{version}` | Tag the committed version. |
| `{version} is already on PyPI; bump [project].version and tag the new version` | Bump it on a PR; PyPI never takes a version twice. |
| `{X.Y.Z} is already on PyPI, so pip never installs an rc of it by default; set [project].version to the next version's rc (for example {X}.{Y}.{Z+1}rc1) and tag that` | Release an rc of the next version. |
| `{version} has no release candidate on PyPI; set [project].version to {X.Y.ZrcN}, tag v{X.Y.ZrcN}, test it with pip install --pre, then release {version}` | Release the rc it names first (steps 1 to 4); it skips any rc already on PyPI, yanked or not. |
| `workflow ref {ref} is not {expected}; release only from publish.yml, started by pushing tag {tag}` | Release only by pushing a tag to this repository. |
| `origin/main is not available; check out with fetch-depth: 0 so the guard can see main` | Restore `fetch-depth: 0` in the guard job's checkout. |
| `HEAD is not on main; tag a commit that is already on main` | Merge first, then tag the commit on `main`. |
| `could not check whether HEAD is on main (git exit {code}: {output}); check that the checkout is a full git clone` | Check the guard job's checkout step, then re-run all jobs. |
| `the pypi environment is missing or unprotected (not found); in repository settings create it with a required reviewer, admins unable to bypass, and deployments limited to v* tags` | Create it as in the one-time setup. If it exists, check that the guard job still has `actions: read` and `GITHUB_TOKEN`. |
| `the pypi environment is missing or unprotected ({gaps}); in repository settings create it with a required reviewer, admins unable to bypass, and deployments limited to v* tags` | Fix each gap it lists with the settings in the one-time setup. |
| `could not read the pypi environment from GitHub (HTTP {status}); try again later` | On 401 or 403, check that the guard job has `actions: read`. Otherwise re-run all jobs later. |

Network or JSON errors: re-run all jobs later.

## Rollback

- Never delete or reuse a version: PyPI refuses a file name it has seen before, forever. Never move or delete a published tag.
- Preferred: revert the bad change on `main` with a PR, then release `X.Y.(Z+1)` through an rc, as above.
- Yank only when the bad version breaks installs. A yanked version is skipped by `pip install langchain-brightdata`, but an exact pin such as `==X.Y.Z` still installs it. Only a PyPI project Owner can yank.
- A yanked version still counts as on PyPI, and a yanked rc no longer counts as the rc for its final.

## If a release run fails

| Job | What failed | What to do |
|---|---|---|
| tests | lint, tests or `--pr` guard from `ci.yml`, on the tagged commit | A flaky failure only needs "Re-run all jobs". Otherwise fix it on a PR, then release the next unused version. |
| guard | a release check | Read the message, see the table above. |
| build | `dist/` did not hold exactly the wheel and sdist for the tag, or the wheel did not install and import | Fix it on a PR, then release the next unused version. |
| publish | the approval was rejected, or the upload failed: usually trusted publishing (OIDC) or the `pypi` environment | Check the PyPI trusted publisher from the one-time setup, then re-run all jobs. |

The next unused version is one with no tag yet (the next rc, or `X.Y.(Z+1)rc1` when `vX.Y.Z` is already tagged), so never move the old tag. To re-run, always use "Re-run all jobs", which is safe because a duplicate upload fails instead of being skipped, never "Re-run failed jobs", which reuses the earlier guard result and build artifact (kept 7 days) so the guard's PyPI checks do not run again.
