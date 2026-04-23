# Consuming the regression workflow from another repo

The reusable workflow at `.github/workflows/regression-test.yml` runs `srcml --parser-test` against a pinned baseline for one `(language, project)` pair and uploads the results as an artifact. To cover multiple pairs, call it once per pair via a matrix.

## Prerequisites

- Your job builds `srcml` and produces a `.deb` installer package (via CPack), then uploads the package(s) as an **actions artifact** before calling this workflow.
- A baseline release must already exist for each pair you invoke. To publish one, run the corresponding `baseline-<language>.yml` workflow in this repo first.
- This repo is public, so the reusable workflow can read baseline releases with the default `GITHUB_TOKEN` — no PAT needed.

## Installer packaging

srcML's build system produces Debian packages through CPack. After a CMake build, run `cpack -G DEB` from the build directory — output appears under `build/dist/` as:

- `srcml_<version>-1_ubuntu<os>_amd64.deb` — the CLI + runtime libs (required).
- `srcml-dev_<version>-1_ubuntu<os>_amd64.deb` — headers / static libs (optional; installed if present).

Upload whichever `.deb` files you have to a single actions artifact. The reusable workflow globs `srcml_*.deb` and `srcml-dev_*.deb` and runs `sudo apt-get install -y` on them, which handles binary + shared-lib placement automatically.

## Example caller (matrix over all languages)

```yaml
name: Large-system regression
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
    strategy:
      fail-fast: false
      matrix:
        target:
          - { language: c,      project: linux  }
          - { language: cpp,    project: llvm   }
          - { language: csharp, project: roslyn }
          - { language: java,   project: jdk    }
          - { language: python, project: django }
    uses: <OWNER>/srcMLLargeSystemTests/.github/workflows/regression-test.yml@mainline
    with:
      srcml-installer-artifact-name: srcml-installer
      language: ${{ matrix.target.language }}
      project: ${{ matrix.target.project }}
      artifact-name: regression-${{ matrix.target.language }}-${{ matrix.target.project }}
      fail-on-regression: true
```

Replace `<OWNER>` with the GitHub user/org that owns this repo. Each matrix leg produces its own results artifact (`regression-<language>-<project>`) so you can inspect them independently even when some pass and some fail. `fail-fast: false` keeps the other legs running when one regresses.

To cover only a subset of pairs, trim the `matrix.target` list. To test a single pair, you can drop the matrix and pass `language:` / `project:` directly.

## Inputs

| Input | Type | Default | Description |
|---|---|---|---|
| `srcml-installer-artifact-name` | string | *required* | Name of the actions artifact containing `srcml*.deb`. |
| `srcml-installer-artifact-run-id` | string | `""` | For cross-workflow-run downloads. Leave empty to read the artifact from the current run. |
| `language` | string | *required* | Language key — must match a `config/<language>.toml` file (`c`, `cpp`, `csharp`, `java`, `python`). |
| `project` | string | *required* | Project name — must match a `[[projects]].name` entry in `config/<language>.toml`. |
| `baseline-release-tag` | string | `""` | Override the per-project `current_baseline_release` from config. Useful for testing against an older baseline. |
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
- `<release-tag>.manifest.json` — which baseline was tested against (language, project, srcml version, project tag, asset name, sha256, etc.).

## Troubleshooting

- **`artifact does not contain any srcml*.deb files`** — your uploaded artifact didn't include a `.deb`. Verify the CPack step ran and produced files under `build/dist/`.
- **`apt-get install -y ./srcml_*.deb` fails with missing dependencies** — the runner may be missing a transitive system package, or the .deb was built for a different Ubuntu version than the runner's. Build the .deb on the same `ubuntu-latest` image that calls the reusable workflow, and make sure `apt-get update` ran.
- **`no current_baseline_release configured for <lang>/<project>`** — no baseline has been published for that pair yet. Run `baseline-<language>.yml` with the chosen `project` input first, merge the resulting pointer-update PR, then retry.
- **Every unit reports as a failure** — likely means the srcML XML format itself changed (different `SRCML_VERSION_STRING`). The baseline archive is no longer comparable — re-roll it against the new srcml.
