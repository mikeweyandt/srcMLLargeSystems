#!/usr/bin/env bash
# Runs `srcml` against a checked-out source tree and produces a compressed baseline archive.
#
# Required environment:
#   SRCML_BIN      path to the srcml binary (default: srcml)
#   SRCML_FLAGS    extra flags as a single space-separated string (e.g. "-r -j 4")
#   INPUT_DIR      directory to process (e.g. ./linux)
#   OUTPUT_XML     path for the raw .xml archive (e.g. baseline-linux-v6.6-srcml-1.1.0.xml)
#   OUTPUT_ZST     path for the compressed archive (e.g. baseline-linux-v6.6-srcml-1.1.0.xml.zst)
#   LOG_FILE       where to tee stdout/stderr (e.g. generate.log)

set -euo pipefail

: "${SRCML_BIN:=srcml}"
: "${SRCML_FLAGS:=-r -j 4 --src-encoding=UTF-8}"
: "${INPUT_DIR:?INPUT_DIR required}"
: "${OUTPUT_XML:?OUTPUT_XML required}"
: "${OUTPUT_ZST:?OUTPUT_ZST required}"
: "${LOG_FILE:=generate.log}"

echo "srcml version: $("$SRCML_BIN" --version)" | tee    "$LOG_FILE"
echo "input dir:    $INPUT_DIR"                 | tee -a "$LOG_FILE"
echo "flags:        $SRCML_FLAGS"                | tee -a "$LOG_FILE"
echo "output xml:   $OUTPUT_XML"                 | tee -a "$LOG_FILE"
echo "start:        $(date --iso-8601=seconds)"  | tee -a "$LOG_FILE"

# shellcheck disable=SC2086
"$SRCML_BIN" $SRCML_FLAGS -o "$OUTPUT_XML" "$INPUT_DIR" 2>&1 | tee -a "$LOG_FILE"

raw_bytes=$(stat -c%s "$OUTPUT_XML")
echo "raw bytes:    $raw_bytes" | tee -a "$LOG_FILE"

zstd -19 --long=27 -T0 --force "$OUTPUT_XML" -o "$OUTPUT_ZST" 2>&1 | tee -a "$LOG_FILE"

zst_bytes=$(stat -c%s "$OUTPUT_ZST")
sha=$(sha256sum "$OUTPUT_ZST" | awk '{print $1}')
echo "zst bytes:    $zst_bytes" | tee -a "$LOG_FILE"
echo "sha256:       $sha"        | tee -a "$LOG_FILE"
echo "end:          $(date --iso-8601=seconds)" | tee -a "$LOG_FILE"

# expose for subsequent workflow steps
{
  echo "raw_bytes=$raw_bytes"
  echo "zst_bytes=$zst_bytes"
  echo "sha256=$sha"
} >> "${GITHUB_OUTPUT:-/dev/null}"
