#!/usr/bin/env bash
# Runs `srcml --parser-test` against a baseline archive and captures stdout/stderr/exit code.
# Never exits non-zero itself — downstream steps decide pass/fail from the captured output.
#
# Required environment:
#   SRCML_BIN   path to the srcml binary under test (default: srcml)
#   BASELINE    path to the decompressed baseline archive (e.g. baseline.xml)
#   OUT_DIR     directory to write parser-test.{stdout,stderr} and exit-code.txt

set -uo pipefail

: "${SRCML_BIN:=srcml}"
: "${BASELINE:?BASELINE required}"
: "${OUT_DIR:?OUT_DIR required}"

mkdir -p "$OUT_DIR"

echo "srcml version:"
"$SRCML_BIN" --version || true

set +e
"$SRCML_BIN" --parser-test --no-color --src-encoding=UTF-8 "$BASELINE" \
  > "$OUT_DIR/parser-test.stdout" \
  2> "$OUT_DIR/parser-test.stderr"
rc=$?
set -e

echo "$rc" > "$OUT_DIR/exit-code.txt"
echo "parser-test exit code: $rc"
echo "stdout bytes: $(stat -c%s "$OUT_DIR/parser-test.stdout")"
echo "stderr bytes: $(stat -c%s "$OUT_DIR/parser-test.stderr")"

exit 0
