# srcMLLargeSystemTests

Regression testing for [srcML](https://www.srcml.org/) against large real-world codebases. The initial corpus is the Linux kernel.

## How it works

1. A pinned release of `srcml` produces a **baseline** srcML archive from a pinned Linux kernel tag. The archive is published as a GitHub Release asset on this repo.
2. Any build of `srcml` (typically a PR to the srcML repo) can be regression-tested by invoking the reusable workflow here. It runs `srcml --parser-test baseline.xml`, which unparses source out of the baseline and reparses it with the candidate `srcml` — any unit whose reparsed srcML differs from the baseline is reported as a failure.

## Layout

- `config/baseline.toml` — pinned versions and the pointer to the current baseline release.
- `.github/workflows/baseline.yml` — manually dispatched workflow that regenerates the baseline.
- `.github/workflows/regression-test.yml` — reusable workflow that downstream repos `uses:` to run regression tests.
- `.github/workflows/full-pipeline-test.yml` — end-to-end self-test: builds srcml from source via the `ci-ubuntu` workflow preset and runs the regression against the current baseline.
- `scripts/` — shell + Python helpers used by the workflows.
- `docs/baseline-process.md` — how to roll a new baseline.
- `docs/consuming.md` — how to invoke the regression workflow from another repo.
- `examples/caller-workflow.yml` — copy-pasteable caller example.
