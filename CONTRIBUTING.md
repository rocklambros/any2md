# Contributing to any2md

This guide covers everything you need to make a change to any2md and get it
merged: development setup, the test commands you'll run, where the code
lives, the coding standards, and the release flow.

For a user-facing orientation, see the [README](README.md). For pipeline
internals and the contracts that converters and pipeline stages have to
honor, see [docs/architecture.md](docs/architecture.md). For the output
shape any change must continue to produce, see
[docs/output-format.md](docs/output-format.md).

## Development setup

Clone the repo and install the editable package with both extras. `dev`
brings in `pytest`, `pytest-snapshot`, `reportlab` (used by the fixture
generator), and `ruff`. `high-fidelity` brings in Docling and roughly 2 GB
of ML models on first use:

```bash
git clone https://github.com/rocklambros/any2md.git
cd any2md
pip install -e ".[dev,high-fidelity]"
pytest
```

You can skip `high-fidelity` if you're working on a non-Docling code path —
the test suite gates Docling-dependent tests with
`@pytest.mark.skipif(not has_docling(), …)` so they're transparently skipped
without it. Coverage of fallback paths is unaffected.

Python 3.10 or later is required.

## Running tests

The default invocation runs the whole suite (currently 172 tests):

```bash
pytest -v
```

Tests are organized by scope:

- `tests/unit/` — pure-function tests for pipeline stages, frontmatter
  helpers, validators, and config parsing.
- `tests/cli/` — `subprocess`-driven tests that exercise the CLI end to end.
- `tests/integration/` — full converter runs over real fixtures, including
  Docling-vs-fallback parity checks.

The integration suite includes snapshot tests that compare converter output
against committed golden files under `tests/fixtures/snapshots/`. When you
make an intentional output change (new pipeline stage, fixed bug that
shifted a hash, etc.), regenerate the snapshots:

```bash
UPDATE_SNAPSHOTS=1 pytest tests/integration/test_snapshots.py
```

Then inspect the diff (`git diff tests/fixtures/snapshots/`) before
committing — the snapshots are review material, not just bytes.

A few tests are network-dependent (the URL converter integration suite)
and opt-in. Run them explicitly when touching `converters/html.py` or the
SSRF protection:

```bash
pytest tests/integration/test_url_wikipedia.py -v
```

## Adding a new converter

The full step-by-step is in
[docs/architecture.md#adding-a-new-converter](docs/architecture.md#adding-a-new-converter).
The short version: write a `convert_<format>` function in
`any2md/converters/<format>.py` that returns `(markdown, SourceMeta)` and
declares its lane (`"structured"` or `"text"`). Register it in
`any2md/cli.py`'s dispatch logic. The frontmatter emitter and the cleanup
pipeline are not the converter's job — keep them centralized.

## Adding a new pipeline stage

The full step-by-step is in
[docs/architecture.md#adding-a-new-pipeline-stage](docs/architecture.md#adding-a-new-pipeline-stage).
The short version: pick the lane (`structured`, `text`, or shared
`cleanup`), write a function with the signature
`(text: str, options: PipelineOptions) -> str`, register it in the lane's
`STAGES` list in dependency order, and add a unit test. One test file per
stage; follow the red-then-green TDD rhythm and commit when green.

## Coding standards

- **Lazy imports for optional dependencies.** Anything pulled in by an
  extra (Docling, reportlab) is imported inside the function that uses it,
  not at module top, so the lightweight install path doesn't pay an import
  cost or crash on missing packages.
- **No class hierarchies for simple operations.** Pipeline stages are
  module-level functions, not subclasses of an abstract `Stage` base.
  Frontmatter helpers are functions, not methods on a `Frontmatter` class.
  This is a deliberate choice — the operations are stateless and the
  resulting code is easier to read.
- **`ruff check` and `ruff format` clean.** The repo runs ruff in CI; PRs
  with lint errors won't merge.
- **Docstrings.** One-line summary, blank line, optional sections (Args,
  Returns, Raises, Examples). Match the style already in
  `any2md/frontmatter.py` and `any2md/pipeline/cleanup.py`.
- **Tests.** One file per stage. Red-then-green TDD: write the failing
  test first, then the minimal implementation. Commit when green. Snapshot
  tests cover whole-converter behavior; unit tests cover individual stages.

## Release flow

Releases are driven by GitHub Releases. The
[`publish.yml`](.github/workflows/publish.yml) workflow inspects the
release's `prerelease` flag: when `prerelease == true`, the artifacts go
to TestPyPI; when `false`, they go to PyPI.

The flow:

1. Bump `__version__` in `any2md/__init__.py` (e.g., `1.0.0rc2` for a
   prerelease, `1.0.0` for a stable).
2. Update `CHANGELOG.md` with a new section dated to the release.
3. Open a PR with the version bump and the changelog entry. Land it.
4. Tag the release commit on `main` (e.g., `git tag -a v1.0.0rc2 -m "any2md 1.0.0rc2"`)
   and push the tag.
5. Create a GitHub Release pointing at the tag. **Mark it as a prerelease**
   if the version contains `a`, `b`, or `rc` — that's what routes the
   workflow to TestPyPI rather than PyPI.
6. Watch the workflow. The version-tag check will fail loudly if the tag
   and `__version__` disagree.

Don't tag and release directly without the PR — CI gates exist for a
reason.

## Pull request process

- Branch off `main` (or off a phase branch like `v1.0` if one is open for
  in-progress work — check the recent activity before branching).
- One logical change per PR. A PR that adds a converter and rewrites the
  HTML lane is two PRs.
- Tests green and `ruff check` clean before requesting review.
- Descriptive PR title — same shape as the commit messages in
  `git log --oneline` (`feat(cli): ...`, `fix(pipeline): ...`,
  `docs: ...`). The title becomes the squash-merge commit message.
- Conversion-quality bug reports are the highest-value issues. If you're
  filing one, please use the `Conversion quality` issue template — it asks
  for the source format, file size, Docling version, full command, and a
  5-line snippet of the bad output, all of which are typically required to
  reproduce the artifact.
