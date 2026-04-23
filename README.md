# srcMLLargeSystemTests

Regression testing for [srcML](https://www.srcml.org/) against large real-world codebases across C, C++, C#, Java, and Python.

## How it works

1. For each `(language, project)` pair declared in `config/<language>.toml`, a pinned release of `srcml` produces a **baseline** srcML archive. Each baseline is published as its own GitHub Release asset on this repo.
2. Any build of `srcml` (typically a PR to the srcML repo) can be regression-tested by invoking the reusable workflow here once per pair. It runs `srcml --parser-test baseline.xml`, which unparses source out of the baseline and reparses it with the candidate `srcml` — any unit whose reparsed srcML differs from the baseline is reported as a failure.

## Layout

- `config/<language>.toml` — per-language pinned versions and the list of projects to baseline for that language. One entry per language: `c`, `cpp`, `csharp`, `java`, `python`.
- `config/migrations.json` — global migration patterns applied across every language.
- `config/<language>.migrations.json` — optional per-language migration patterns, layered on top of the global ones.
- `.github/actions/generate-baseline/` — composite action that does the actual baseline generation; reused by every `baseline-<language>.yml`.
- `.github/workflows/baseline-<language>.yml` — one manually-dispatched workflow per language for regenerating that language's baselines. Each takes a `project` input to pick which `[[projects]]` row to roll.
- `.github/workflows/regression-test.yml` — reusable workflow that downstream repos `uses:` to run a regression test for one `(language, project)` pair. Callers typically invoke it via a matrix.
- `.github/workflows/full-pipeline-test.yml` — end-to-end self-test: builds srcml from source via the `ci-ubuntu` workflow preset and runs the regression against every pair in one matrix.
- `scripts/` — shell + Python helpers used by the workflows.
- `docs/baseline-process.md` — how to roll a new baseline and how to add a project.
- `docs/consuming.md` — how to invoke the regression workflow from another repo.
- `examples/caller-workflow.yml` — copy-pasteable caller example with the full matrix.
