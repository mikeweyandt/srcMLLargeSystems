# Rolling a new baseline

A baseline is a compressed srcML archive of a specific project at a specific VCS tag, produced by a specific released `srcml`. Each baseline is scoped to one `(language, project)` pair and is stored as a GitHub Release asset on this repo.

## When to roll

- A new srcML release is published and you want future regression runs to test against it.
- You want to move a project to a newer VCS tag.
- The srcML XML format changes (bump in `SRCML_VERSION_STRING`) and old baselines are no longer comparable.
- You add a new project to a language's `config/<language>.toml` and need an initial baseline for it.

## How

1. In a branch, edit the relevant `config/<language>.toml`:
   - Change `.srcml.version` if bumping srcML.
   - Change the `[[projects]]` entry's `tag` if moving to a newer project release.
   - **Do not** edit `current_baseline_release` manually; the workflow opens a PR to update it.
2. Push the branch.
3. In the GitHub Actions UI, run the language-specific **Generate baseline — \<Language\>** workflow manually (`workflow_dispatch`):
   - `project`: pick the project you're rolling (required).
   - `srcml_version` / `project_tag`: optional overrides for experimentation.
   - `dry_run`: set to `true` to produce a workflow artifact without creating a release or opening a PR.
4. The workflow:
   - Installs the pinned srcml release `.deb`.
   - Shallow-clones the project at the configured tag (optionally narrowed to the configured `subdir`).
   - Runs `srcml` against the tree with the configured flags.
   - Compresses the archive with `zstd -19 --long=27`.
   - Publishes `<release-tag>.xml.zst` + `<release-tag>.manifest.json` + `<release-tag>.generate.log` as a GitHub Release named `<release-tag>`, where **`<release-tag>` = `baseline-<language>-<project>-<project_tag>-srcml-<srcml_version>`**.
   - Opens a PR bumping the matching `[[projects]]` entry's `current_baseline_release` in `config/<language>.toml`.
5. Review and merge the PR. Downstream consumers automatically pick up the new baseline on their next run.

## Release tag format

`baseline-<language>-<project>-<project_tag>-srcml-<srcml_version>`

Examples:

- `baseline-c-linux-v6.6-srcml-1.1.0`
- `baseline-cpp-llvm-llvmorg-19.1.0-srcml-1.1.0`
- `baseline-java-jdk-jdk-21+35-srcml-1.1.0`

## Expected runtime

Full-project generation on `ubuntu-latest` is expected to take between a few minutes (Django, Roslyn) and several hours (LLVM, OpenJDK, Linux kernel). Each workflow has a 300-minute step timeout. If any project exceeds ~4 hours on a GitHub-hosted runner (6h hard ceiling), migrate that language's `runs-on:` to a self-hosted runner with more CPU.

## Dry-run

Pass `dry_run: true` to build the archive and upload it as a workflow artifact without creating a release or opening a PR. Useful for experimenting with srcml flags before committing to a release, or for validating that a newly added project in `config/<language>.toml` produces a sensible archive.

## Archive size

Raw srcML of a large project (kernel, LLVM, JDK) is expected in the low-single-digit GB range; compressed with `zstd -19` should be well under 500 MB. GitHub Release assets have a 2 GB UI / 5 GB API limit per asset — if we exceed it, split the archive or fall back to LFS.

## Adding a new project

1. Append a new `[[projects]]` block to `config/<language>.toml`:
   ```toml
   [[projects]]
   name = "<short-name>"
   repo = "https://github.com/<org>/<repo>.git"
   tag  = "<vcs-tag>"
   # subdir = "relative/path"            # optional
   # srcml_flags_append = ["--flag"]     # optional
   # exclude_files = ["path/to/problematic.py"]   # optional; rm'd after clone (warn-if-missing)
   current_baseline_release = ""
   ```
2. Add the new `<short-name>` to the `project:` choice `options:` list in `.github/workflows/baseline-<language>.yml`.
3. Add a new matrix entry `- { language: <lang>, project: <short-name> }` to `full-pipeline-test.yml` (and to downstream `caller-workflow.yml` consumers) if it should run as part of the standard regression sweep.
4. Run `baseline-<language>.yml` with `project: <short-name>` to publish the first baseline.
