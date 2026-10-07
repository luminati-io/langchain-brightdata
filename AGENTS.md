# AGENTS.md

Rules for coding agents, and people, working on langchain-brightdata: LangChain tools for Bright Data's web data APIs, released to PyPI from this repository. Some files here are release machinery, so read the hard rules before touching them. Release steps are in `RELEASING.md`.

## Commands

Run from the repository root in a virtual environment (CI tests Python 3.9 and 3.13):

```sh
pip install -e ".[dev]"
python -m pytest -q
ruff check .
python scripts/release_guard.py --pr
```

All of them must pass before a PR is ready; CI runs the same commands. ruff is pinned in two places, the dev extra in `pyproject.toml` and `.github/workflows/ci.yml`: keep them in sync. The packaging pin is shared the same way by `ci.yml` and `publish.yml`.

## Hard rules

- Never rename the repository or `.github/workflows/publish.yml`. PyPI trusts uploads only from that file in this repository.
- Keep the PyPI upload step directly in `publish.yml`. Never move it into a reusable workflow or a composite action.
- Never add `skip-existing` to the upload step. The guard fails on any mention of it in `publish.yml`, comments included, so never write that name anywhere in that file.
- Never change `[project].name` in `pyproject.toml`. Change `[project].version` only when the maintainer asks.
- Never rewrite the version inside a workflow. The release version is the one committed in `pyproject.toml`.
- Tests stay offline. pytest-socket blocks the network and `tests/conftest.py` forces a fake API key. Never use a real key in tests.
- `tests/fixtures/` holds scrubbed recordings of real API replies. Never commit a real API key, zone name or customer data. Only a maintainer re-records them.
- `tests/unit_tests/snapshots/tool_contract.json` records what an LLM sees from each tool. Change it only on purpose (`UPDATE_TOOL_CONTRACT=1`, see `tests/unit_tests/test_tool_contract.py`) and get the diff reviewed.
- Never push `v*` tags and never approve the `pypi` environment. Releases belong to the maintainer.
- Never edit `publish.yml`, `ci.yml`, `scripts/release_guard.py`, `RELEASING.md` or `AGENTS.md` without the maintainer's review.
- Pin every new GitHub Action by full commit SHA with a version comment, like the existing steps: `uses: owner/action@<full sha> # vX.Y.Z`.

## Where things are

- `langchain_brightdata/`: the package. `brightdata_search.py` (BrightDataSERP), `brightdata_unlocker.py` (BrightDataUnlocker), `brightdata_scraper.py` (BrightDataWebScraperAPI and its dataset ids), `_utilities.py` (API wrappers).
- `tests/conftest.py`: the fake key every test gets.
- `tests/unit_tests/`: offline, replay, LangChain standard, tool contract and release guard tests.
- `tests/fixtures/`: the recorded replies the replay tests serve.
- `scripts/release_guard.py`: release checks, `--pr` on every PR and `--tag` in `publish.yml`.
- `.github/workflows/ci.yml`: lint, tests, guard, and `ci-ok`, the required check.
- `.github/workflows/publish.yml`: the only workflow that uploads to PyPI.
- `.github/dependabot.yml`: weekly updates for the pinned actions.
