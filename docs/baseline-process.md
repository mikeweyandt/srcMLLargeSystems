# Rolling a new baseline

The baseline is a compressed srcML archive of a specific Linux kernel tag, produced by a specific released `srcml`. It is stored as a GitHub Release asset on this repo.

## When to roll

- A new srcML release is published and you want future regression runs to test against it.
- You want to move to a newer Linux kernel tag.
- The srcML XML format changes (bump in `SRCML_VERSION_STRING`) and old baselines are no longer comparable.

## How

1. Open `config/baseline.toml` in a branch and edit the relevant fields — `srcml.version`, `kernel.tag`. Do **not** edit `current_baseline_release` manually; the workflow opens a PR to update it.
2. Push the branch.
3. In the GitHub Actions UI, run the **Generate baseline** workflow manually (`workflow_dispatch`). Optionally override `srcml_version` / `kernel_tag` / `dry_run` for experimentation.
4. The workflow:
   - Installs the pinned srcml release `.deb`.
   - Shallow-clones the kernel at the pinned tag.
   - Runs `srcml` against the kernel tree.
   - Compresses the archive with `zstd -19`.
   - Publishes `<release-tag>.xml.zst` + `<release-tag>.manifest.json` + `<release-tag>.generate.log` as a GitHub Release named `<release-tag>`, where `<release-tag>` is `baseline-linux-<kernel_tag>-srcml-<srcml_version>`.
   - Opens a PR bumping `current_baseline_release` in `config/baseline.toml`.
5. Review and merge the PR. Downstream consumers automatically pick up the new baseline on their next run.

## Expected runtime

Full kernel generation on `ubuntu-latest` is expected to take 1–3 hours. The step has a 300-minute timeout. If it exceeds ~4 hours on a GitHub-hosted runner (6h hard ceiling), migrate `runs-on:` to a self-hosted runner with more CPU.

## Dry-run

Pass `dry_run: true` to build the archive and upload it as a workflow artifact without creating a release or opening a PR. Useful for experimenting with srcml flags before committing to a release.

## Archive size

Raw srcML of the full Linux kernel is expected in the low-single-digit GB range; compressed with `zstd -19` should be well under 500 MB. GitHub Release assets have a 2 GB UI / 5 GB API limit per asset — if we exceed it, split the archive or fall back to LFS.
