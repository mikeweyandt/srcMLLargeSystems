# Consuming the regression workflow from another repo

The reusable workflow at `.github/workflows/regression-test.yml` runs `srcml --parser-test` against the baseline and uploads the results as an artifact.

## Prerequisites

- Your job builds `srcml` and produces a `.deb` installer package (via CPack), then uploads the package(s) as an **actions artifact** before calling this workflow.
- This repo is public, so the reusable workflow can read the baseline release with the default `GITHUB_TOKEN` — no PAT needed.

## Installer packaging

srcML's build system produces Debian packages through CPack. After a CMake build, run `cpack -G DEB` from the build directory — output appears under `build/dist/` as:

- `srcml_<version>-1_ubuntu<os>_amd64.deb` — the CLI + runtime libs (required).
- `srcml-dev_<version>-1_ubuntu<os>_amd64.deb` — headers / static libs (optional; installed if present).

Upload whichever `.deb` files you have to a single actions artifact. The reusable workflow globs `srcml_*.deb` and `srcml-dev_*.deb` and runs `sudo apt-get install -y` on them, which handles binary + shared-lib placement automatically.

## Example caller

```yaml
name: Large-system regression (Linux kernel)
on:
  pull_request:
  workflow_dispatch:

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install build deps
        run: |
          sudo apt-get update
          sudo apt-get install -y \
            cmake ninja-build g++ dpkg-dev \
            libarchive-dev libcurl4-openssl-dev \
            libxml2-dev libxml2-utils libxslt1-dev
      - name: Build srcml
        run: |
          cmake -S . -B build --preset ci-linux
          cmake --build build -j
      - name: Package .deb via CPack
        working-directory: build
        run: cpack -G DEB
      - name: Collect installer artifacts
        run: |
          mkdir -p installer
          cp build/dist/srcml_*.deb     installer/
          cp build/dist/srcml-dev_*.deb installer/ 2>/dev/null || true
      - uses: actions/upload-artifact@v4
        with:
          name: srcml-installer
          path: installer/
          if-no-files-found: error

  regression:
    needs: build
    uses: <OWNER>/srcMLLargeSystemTests/.github/workflows/regression-test.yml@mainline
    with:
      srcml-installer-artifact-name: srcml-installer
      fail-on-regression: true
```

Replace `<OWNER>` with the GitHub user/org that owns this repo.

## Inputs

| Input | Type | Default | Description |
|---|---|---|---|
| `srcml-installer-artifact-name` | string | *required* | Name of the actions artifact containing `srcml*.deb`. |
| `srcml-installer-artifact-run-id` | string | `""` | For cross-workflow-run downloads. Leave empty to read the artifact from the current run. |
| `baseline-release-tag` | string | `""` | Override `current_baseline_release` from `config/baseline.toml`. |
| `fail-on-regression` | boolean | `true` | Fail the workflow when regressions are found. Set `false` to keep green but still produce artifacts. |
| `artifact-name` | string | `srcml-regression-results` | Name for the uploaded results artifact. |

## Outputs

| Output | Description |
|---|---|
| `regressions-found` | `"true"` or `"false"`. |
| `summary` | One-line summary (total / failed / per-language). |

## What's in the results artifact

- `parser-test.stdout` / `parser-test.stderr` — raw output.
- `grouped-failures.md` — human-readable report: totals per language, top failure signatures with representative diffs.
- `summary.txt` — one-line machine-readable counts.
- `exit-code.txt` — raw exit code of `srcml --parser-test`.
- `<release-tag>.manifest.json` — which baseline was tested against (srcml version, kernel tag, asset name, sha256, etc.).

## Troubleshooting

- **`artifact does not contain any srcml*.deb files`** — your uploaded artifact didn't include a `.deb`. Verify the CPack step ran and produced files under `build/dist/`.
- **`apt-get install -y ./srcml_*.deb` fails with missing dependencies** — the runner may be missing a transitive system package, or the .deb was built for a different Ubuntu version than the runner's. Build the .deb on the same `ubuntu-latest` image that calls the reusable workflow, and make sure `apt-get update` ran.
- **Every unit reports as a failure** — likely means the srcML XML format itself changed (different `SRCML_VERSION_STRING`). The baseline archive is no longer comparable — re-roll it against the new srcml.
