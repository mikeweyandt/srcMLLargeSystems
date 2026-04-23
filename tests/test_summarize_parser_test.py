"""Tests for scripts/summarize_parser_test.py.

Runnable with either `pytest tests/` or `python -m unittest discover tests`.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import summarize_parser_test as s  # noqa: E402


FIX = REPO_ROOT / "tests" / "fixtures"


def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


class AllPassFixture(unittest.TestCase):
    def test_counts_and_empty_failures(self):
        report = s.parse(_read("all_pass.stdout"))
        self.assertEqual(report.total, 15)
        self.assertEqual(report.failed, 0)
        self.assertEqual(report.per_language_totals, {"C": (0, 10), "C++": (0, 5)})
        self.assertEqual(report.failures, [])

    def test_markdown_says_clean(self):
        report = s.parse(_read("all_pass.stdout"))
        md = s.render_grouped_markdown(report)
        self.assertIn("No failing units", md)


class MixedFailuresFixture(unittest.TestCase):
    def test_counts(self):
        report = s.parse(_read("mixed_failures.stdout"))
        self.assertEqual(report.total, 9)
        self.assertEqual(report.failed, 3)
        self.assertEqual(report.per_language_totals, {"C": (2, 6), "C++": (1, 3)})

    def test_failures_extracted(self):
        report = s.parse(_read("mixed_failures.stdout"))
        self.assertEqual(len(report.failures), 3)
        self.assertEqual({f.language for f in report.failures}, {"C", "C++"})
        self.assertEqual(sorted(f.unit for f in report.failures), [2, 2, 4])
        for f in report.failures:
            self.assertTrue(f.signature_hash)
            self.assertTrue(f.test_region)
            self.assertTrue(f.srcml_region)

    def test_summary_line(self):
        report = s.parse(_read("mixed_failures.stdout"))
        line = s.render_summary(report)
        self.assertIn("total=9", line)
        self.assertIn("failed=3", line)

    def test_markdown_contains_groups_and_diff(self):
        report = s.parse(_read("mixed_failures.stdout"))
        md = s.render_grouped_markdown(report)
        self.assertIn("Failure groups", md)
        self.assertIn("```diff", md)


class MalformedFallback(unittest.TestCase):
    def test_falls_back_to_raw(self):
        report = s.parse(_read("malformed.stdout"))
        self.assertEqual(report.failures, [])
        self.assertTrue(report.parse_warning)
        self.assertEqual(report.total, 10)
        self.assertEqual(report.failed, 5)
        md = s.render_grouped_markdown(report)
        self.assertIn("Parse warning", md)
        self.assertIn("some text that does not match", md)


class EmptyInput(unittest.TestCase):
    def test_handles_empty(self):
        report = s.parse("")
        self.assertEqual(report.failures, [])
        self.assertEqual(report.total, 0)
        self.assertEqual(report.failed, 0)
        md = s.render_grouped_markdown(report)
        self.assertIn("No failing units", md)


class StackedMigrations(unittest.TestCase):
    """Global migrations layered with language-specific migrations.

    Regression test for the --migrations flag being repeatable so that a
    cross-language file and a per-language file can both contribute patterns.
    """

    def _run_main(self, stdout_text: str, migration_files: list[Path]) -> tuple[str, str]:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            stdout_path = tmpdir / "parser-test.stdout"
            stdout_path.write_text(stdout_text, encoding="utf-8")
            out_md = tmpdir / "grouped.md"
            out_summary = tmpdir / "summary.txt"
            argv = [
                str(stdout_path),
                "--out", str(out_md),
                "--summary", str(out_summary),
            ]
            for mf in migration_files:
                argv += ["--migrations", str(mf)]
            rc = s.main(argv)
            self.assertEqual(rc, 0)
            return out_md.read_text(encoding="utf-8"), out_summary.read_text(encoding="utf-8")

    def test_patterns_stack_from_two_files(self):
        """Two files, each contributing one pattern that matches a distinct failure.

        Uses the mixed_failures fixture which has C and C++ failures whose
        regions don't match by default. Each migration file rewrites one side
        with a whole-region replacement so both failures become migrated.
        """
        report = s.parse(_read("mixed_failures.stdout"))
        self.assertEqual(len(report.failures), 3, "fixture precondition")

        f_c = next(f for f in report.failures if f.language == "C")
        f_cpp = next(f for f in report.failures if f.language == "C++")

        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            global_file = tmpdir / "global.json"
            lang_file = tmpdir / "c.json"
            global_file.write_text(json.dumps({
                "patterns": [{
                    "name": "from-global",
                    "description": "rewrites C test region to match its srcml region",
                    "replacements": [[f_c.test_region, f_c.srcml_region]],
                }]
            }), encoding="utf-8")
            lang_file.write_text(json.dumps({
                "patterns": [{
                    "name": "from-language",
                    "description": "rewrites C++ test region to match its srcml region",
                    "replacements": [[f_cpp.test_region, f_cpp.srcml_region]],
                }]
            }), encoding="utf-8")

            patterns = s.load_migrations(global_file) + s.load_migrations(lang_file)
            self.assertEqual([p.name for p in patterns], ["from-global", "from-language"])
            self.assertEqual(s.classify_migration(f_c, patterns), ["from-global"])
            self.assertEqual(s.classify_migration(f_cpp, patterns), ["from-language"])

    def test_main_accepts_repeated_migrations_flag(self):
        """Argparse append: --migrations can appear multiple times on the CLI."""
        report = s.parse(_read("mixed_failures.stdout"))
        f_c = next(f for f in report.failures if f.language == "C")

        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            global_file = tmpdir / "global.json"
            lang_file = tmpdir / "lang.json"
            global_file.write_text(json.dumps({
                "patterns": [{
                    "name": "global-matches-c",
                    "description": "",
                    "replacements": [[f_c.test_region, f_c.srcml_region]],
                }]
            }), encoding="utf-8")
            lang_file.write_text(json.dumps({"patterns": []}), encoding="utf-8")

            md, _summary = self._run_main(_read("mixed_failures.stdout"), [global_file, lang_file])
            self.assertIn("Migrated failures (suppressed)", md)
            self.assertIn("global-matches-c", md)


if __name__ == "__main__":
    unittest.main()
