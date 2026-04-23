#!/usr/bin/env python3
"""Post-process `srcml --parser-test` output into a grouped failure report.

The parser-test output format is governed by
src/client/ParserTest.cpp in the srcML repo. Under --no-color the layout is:

    \\n<lang>(padded12)<url>(padded30)<unit-numbers-and-dashes...>

    (repeated per input archive)

    \\n\\nErrors:\\n
    <lang>\\t<url>\\t<filename>\\t<unit#>\\n
     test:\\n
    <sxml diff region>\\n
    srcml:\\n
    <ssout diff region>\\n
    (repeated per failing unit)

    \\n\\nSummary:\\n
    <sorted per-file failure lines>

    \\nCounts: Total <failed>(w6) <total>(w6)\\t<percent>%\\n
            <lang>(w12) <failed>(w6) <total>(w6)\\t<percent>%\\n
            (repeated per language)

This script slices on those section headers and produces:
  - summary.txt         — one-line machine-readable counts
  - grouped-failures.md — human-readable report grouped by language & signature

On any parse surprise it falls back to emitting the raw Errors section
verbatim with a banner, so the artifact remains useful.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
ERROR_HEADER_RE = re.compile(r"^([A-Za-z][A-Za-z+#0-9]*)\t([^\t\n]*)\t([^\t\n]*)\t(\d+)$")
COUNTS_TOTAL_RE = re.compile(r"^Counts:\s+Total\s+(\d+)\s+(\d+)\s+(?:<1|\d+(?:\.\d+)?)%", re.M)
COUNTS_LANG_RE = re.compile(r"^\s{8}(\S+)\s+(\d+)\s+(\d+)\s+(?:<1|\d+(?:\.\d+)?)%", re.M)


@dataclass
class Failure:
    language: str
    url: str
    filename: str
    unit: int
    test_region: str
    srcml_region: str
    signature: str = ""
    signature_hash: str = ""
    source_filename: str = ""
    migrated_by: list[str] = field(default_factory=list)  # names of the migration patterns that made this failure equivalent


@dataclass
class MigrationPattern:
    name: str
    description: str
    # Each replacement is ("literal"|"regex", src, dst).
    # Regex dst uses Python backref syntax (\1, \g<name>).
    replacements: list[tuple[str, str, str]]

    def apply(self, text: str) -> str:
        for kind, src, dst in self.replacements:
            if kind == "regex":
                text = re.sub(src, dst, text)
            else:
                text = text.replace(src, dst)
        return text


def load_migrations(path: Path) -> list[MigrationPattern]:
    """Load migration patterns from a JSON config.

    File shape:
        {"patterns": [
            {"name": "...", "description": "...",
             "replacements": [
                 ["from", "to"],                            # literal string replace
                 {"from": "...", "to": "..."},              # literal (dict form)
                 {"regex": "...", "replace": "..."}         # regex replace
             ]},
            ...
        ]}
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    out: list[MigrationPattern] = []
    for p in data.get("patterns", []):
        name = p.get("name") or "unnamed"
        desc = p.get("description", "")
        raw_reps = p.get("replacements") or []
        reps: list[tuple[str, str, str]] = []
        for r in raw_reps:
            if isinstance(r, dict):
                if "regex" in r:
                    reps.append(("regex", r["regex"], r["replace"]))
                else:
                    reps.append(("literal", r["from"], r["to"]))
            else:
                reps.append(("literal", r[0], r[1]))
        out.append(MigrationPattern(name=name, description=desc, replacements=reps))
    return out


def classify_migration(f: Failure, patterns: list[MigrationPattern]) -> list[str]:
    """Return the names of the pattern(s) that equalize the two regions.

    Tries each pattern alone first. If none match individually, applies patterns
    cumulatively in declaration order; if that equalizes, returns the names of
    every pattern that actually changed the text.
    """
    for p in patterns:
        if p.apply(f.test_region) == f.srcml_region:
            return [p.name]

    text = f.test_region
    applied: list[str] = []
    for p in patterns:
        new_text = p.apply(text)
        if new_text != text:
            applied.append(p.name)
            text = new_text
    if text == f.srcml_region:
        return applied
    return []


@dataclass
class ParsedReport:
    failures: list[Failure] = field(default_factory=list)
    total: int = 0
    failed: int = 0
    per_language_totals: dict[str, tuple[int, int]] = field(default_factory=dict)  # lang -> (failed, total)
    raw_errors_section: str = ""
    raw_counts_section: str = ""
    parse_warning: str = ""


def strip_ansi(s: str) -> str:
    return ANSI_RE.sub("", s)


def first_meaningful_line(block: str) -> str:
    for line in block.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def make_signature(f: Failure) -> str:
    """A compact, whitespace-normalized identifier for a failure's first diff line.

    Used to collapse "same bug hit N times" into a single group.
    """
    probe = first_meaningful_line(f.test_region) or first_meaningful_line(f.srcml_region)
    return re.sub(r"\s+", " ", probe)[:200]


def parse(stdout: str) -> ParsedReport:
    report = ParsedReport()
    text = strip_ansi(stdout)

    errors_marker = "\nErrors:\n"
    summary_marker = "\nSummary:\n"

    errors_idx = text.find(errors_marker)
    if errors_idx == -1:
        # no failures reported; still try to pick up Counts: for totals
        _extract_counts(text, report)
        return report

    after_errors = text[errors_idx + len(errors_marker):]

    summary_idx = after_errors.find(summary_marker)
    if summary_idx == -1:
        errors_blob = after_errors
        counts_blob = ""
    else:
        errors_blob = after_errors[:summary_idx]
        counts_blob = after_errors[summary_idx:]

    report.raw_errors_section = errors_blob.strip("\n")
    report.raw_counts_section = counts_blob

    _extract_counts(counts_blob or text, report)
    _extract_failures(errors_blob, report)

    if not report.failures and report.raw_errors_section:
        report.parse_warning = (
            "Errors section was present but no per-unit records could be parsed — "
            "parser-test output format may have drifted. Raw section included below."
        )

    return report


def _extract_counts(text: str, report: ParsedReport) -> None:
    m = COUNTS_TOTAL_RE.search(text)
    if m:
        report.failed = int(m.group(1))
        report.total = int(m.group(2))
    for m in COUNTS_LANG_RE.finditer(text):
        lang, failed, total = m.group(1), int(m.group(2)), int(m.group(3))
        report.per_language_totals[lang] = (failed, total)


def _extract_failures(errors_blob: str, report: ParsedReport) -> None:
    lines = errors_blob.split("\n")
    header_positions: list[tuple[int, re.Match[str]]] = []
    for i, line in enumerate(lines):
        m = ERROR_HEADER_RE.match(line)
        if m:
            header_positions.append((i, m))

    for idx, (line_no, header_match) in enumerate(header_positions):
        next_line_no = header_positions[idx + 1][0] if idx + 1 < len(header_positions) else len(lines)
        block_lines = lines[line_no + 1:next_line_no]
        test_region, srcml_region = _split_test_srcml(block_lines)

        f = Failure(
            language=header_match.group(1),
            url=header_match.group(2),
            filename=header_match.group(3),
            unit=int(header_match.group(4)),
            test_region=test_region,
            srcml_region=srcml_region,
        )
        f.signature = make_signature(f)
        f.signature_hash = hashlib.sha1(f.signature.encode("utf-8", "replace")).hexdigest()[:10]
        report.failures.append(f)


def lookup_unit_metadata(archive_path: Path, needed: set[int]) -> dict[int, str]:
    """Return {unit_no: filename} for the requested units.

    Unit numbers are 1-indexed positions of nested <unit> elements under the root,
    matching how `srcml --parser-test` numbers them. Stops reading once the highest
    needed unit has been seen. Returns an empty dict on any parse error so the
    report still renders without this annotation.
    """
    if not needed:
        return {}
    max_needed = max(needed)
    result: dict[int, str] = {}
    count = 0
    root_seen = False

    try:
        for event, elem in ET.iterparse(str(archive_path), events=("start", "end")):
            tag = elem.tag.rpartition("}")[2] or elem.tag
            if tag != "unit":
                continue
            if event == "start":
                if not root_seen:
                    root_seen = True
                    continue
                count += 1
                if count in needed:
                    result[count] = elem.attrib.get("filename", "")
                if count >= max_needed:
                    break
            else:  # end
                elem.clear()
    except ET.ParseError:
        pass

    return result


def _split_test_srcml(block_lines: list[str]) -> tuple[str, str]:
    test_idx = None
    srcml_idx = None
    for i, line in enumerate(block_lines):
        stripped = line.lstrip()
        if test_idx is None and stripped == "test:":
            test_idx = i
        elif srcml_idx is None and stripped == "srcml:":
            srcml_idx = i
            break
    if test_idx is None or srcml_idx is None:
        return "", "\n".join(block_lines).strip("\n")
    test_region = "\n".join(block_lines[test_idx + 1:srcml_idx]).strip("\n")
    srcml_region = "\n".join(block_lines[srcml_idx + 1:]).strip("\n")
    return test_region, srcml_region


def render_summary(report: ParsedReport) -> str:
    langs = ",".join(
        f"{lang}:{failed}/{total}"
        for lang, (failed, total) in sorted(report.per_language_totals.items())
    )
    return f"total={report.total} failed={report.failed} langs={langs or '-'}\n"


def render_grouped_markdown(
    report: ParsedReport,
    excluded_files: list[str] | tuple[str, ...] = (),
) -> str:
    lines: list[str] = []
    lines.append("# srcML parser-test regression report")
    lines.append("")
    lines.append(f"- **Total units tested**: {report.total}")
    lines.append(f"- **Failed**: {report.failed}")

    migrated = [f for f in report.failures if f.migrated_by]
    real = [f for f in report.failures if not f.migrated_by]
    if migrated:
        lines.append(f"- **Suppressed by migrations**: {len(migrated)}")
        lines.append(f"- **Remaining failures**: {len(real)}")
    if excluded_files:
        lines.append(f"- **Files excluded from baseline**: {len(excluded_files)}")

    if report.per_language_totals:
        lines.append("")
        lines.append("## Failures by language (reported by parser-test)")
        lines.append("")
        lines.append("| Language | Failed | Total |")
        lines.append("|---|---:|---:|")
        for lang, (failed, total) in sorted(report.per_language_totals.items()):
            lines.append(f"| {lang} | {failed} | {total} |")

    if report.parse_warning:
        lines.append("")
        lines.append("> **Parse warning:** " + report.parse_warning)
        lines.append("")
        lines.append("```")
        lines.append(report.raw_errors_section[:20000])
        if len(report.raw_errors_section) > 20000:
            lines.append("... (truncated)")
        lines.append("```")
        return "\n".join(lines) + "\n"

    if migrated:
        by_pattern: dict[str, int] = defaultdict(int)
        for f in migrated:
            for name in f.migrated_by:
                by_pattern[name] += 1
        lines.append("")
        lines.append("## Migrated failures (suppressed)")
        lines.append("")
        lines.append("| Pattern | Count |")
        lines.append("|---|---:|")
        for name, count in sorted(by_pattern.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"| `{name}` | {count} |")
        lines.append("")
        lines.append(
            "> These failures had a known markup-level migration pattern applied and, after "
            "substitution, the two sides matched. See `config/migrations.json` for definitions."
        )

    if excluded_files:
        lines.append("")
        lines.append("## Files excluded from baseline")
        lines.append("")
        lines.append(
            "These paths were removed from the project source tree before srcml ran, "
            "per `exclude_files` in `config/<language>.toml`."
        )
        lines.append("")
        for p in excluded_files:
            lines.append(f"- `{p}`")

    if not report.failures:
        lines.append("")
        lines.append("No failing units — parser-test reports clean against the baseline.")
        return "\n".join(lines) + "\n"

    if not real:
        lines.append("")
        lines.append("All failures are accounted for by migration patterns.")
        return "\n".join(lines) + "\n"

    groups: dict[tuple[str, str], list[Failure]] = defaultdict(list)
    for f in real:
        groups[(f.language, f.signature_hash)].append(f)

    ranked = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))

    lines.append("")
    lines.append(f"## Failure groups ({len(ranked)} unique signatures across {len(real)} failing units)")
    lines.append("")

    for (lang, sig_hash), failures in ranked:
        rep = failures[0]
        lines.append(f"### [{lang}] signature `{sig_hash}` — {len(failures)} occurrence(s)")
        lines.append("")
        if rep.signature:
            lines.append(f"**First differing line:** `{rep.signature[:160]}`")
            lines.append("")
        header_suffix = f", source `{rep.source_filename}`" if rep.source_filename else f", archive `{rep.filename}`"
        lines.append(f"**Representative diff (unit #{rep.unit}{header_suffix}):**")
        lines.append("")
        lines.append("```diff")
        for line in rep.test_region.splitlines()[:40]:
            lines.append("- " + line)
        if len(rep.test_region.splitlines()) > 40:
            lines.append("- ... (test region truncated)")
        for line in rep.srcml_region.splitlines()[:40]:
            lines.append("+ " + line)
        if len(rep.srcml_region.splitlines()) > 40:
            lines.append("+ ... (srcml region truncated)")
        lines.append("```")
        lines.append("")
        if any(f.source_filename for f in failures):
            lines.append("**Affected units:**")
            lines.append("")
            for f in failures[:21]:
                if f.source_filename:
                    lines.append(f"- #{f.unit} — `{f.source_filename}`")
                else:
                    lines.append(f"- #{f.unit}")
            if len(failures) > 21:
                lines.append(f"- ... ({len(failures) - 21} more)")
            lines.append("")
        elif len(failures) > 1:
            other_units = ", ".join(str(f.unit) for f in failures[1:21])
            suffix = "" if len(failures) <= 21 else f", ... ({len(failures) - 21} more)"
            lines.append(f"**Other affected units:** {other_units}{suffix}")
            lines.append("")

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    p.add_argument("stdout_path", help="Path to the captured parser-test stdout")
    p.add_argument("--out", default="grouped-failures.md", help="Path for the grouped markdown report")
    p.add_argument("--summary", default="summary.txt", help="Path for the one-line summary")
    p.add_argument("--archive", default=None,
                   help="Path to the srcML archive (e.g. baseline.xml). When provided, "
                        "the report annotates each failing unit with its source filename.")
    p.add_argument("--migrations", action="append", default=None,
                   help="Path to a migrations JSON file. Repeatable: pass --migrations multiple "
                        "times to stack patterns (e.g. a global file plus a language-specific one). "
                        "Patterns are applied in the order the files are given. Failures whose test "
                        "region becomes equal to the srcml region after applying a pattern's "
                        "replacements are classified as migrated and suppressed from the "
                        "failure-groups section.")
    p.add_argument("--manifest", default=None,
                   help="Path to the baseline manifest.json. When provided, the report "
                        "includes the list of files excluded from the baseline source "
                        "tree (manifest key: excluded_files).")
    args = p.parse_args(argv)

    raw = Path(args.stdout_path).read_text(encoding="utf-8", errors="replace")
    report = parse(raw)

    if args.archive and report.failures:
        needed = {f.unit for f in report.failures}
        meta = lookup_unit_metadata(Path(args.archive), needed)
        for f in report.failures:
            f.source_filename = meta.get(f.unit, "")

    patterns: list[MigrationPattern] = []
    if args.migrations:
        for path in args.migrations:
            patterns.extend(load_migrations(Path(path)))
        for f in report.failures:
            f.migrated_by = classify_migration(f, patterns)

    excluded_files: list[str] = []
    if args.manifest:
        try:
            m = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        except Exception as e:
            print(f"warning: could not read --manifest {args.manifest}: {e}", file=sys.stderr)
        else:
            raw = m.get("excluded_files") or []
            if isinstance(raw, list):
                excluded_files = [str(x) for x in raw]

    Path(args.summary).write_text(render_summary(report), encoding="utf-8")
    Path(args.out).write_text(
        render_grouped_markdown(report, excluded_files=excluded_files),
        encoding="utf-8",
    )

    sys.stdout.write(render_summary(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
