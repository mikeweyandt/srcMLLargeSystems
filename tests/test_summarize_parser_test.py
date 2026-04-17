"""Tests for scripts/summarize_parser_test.py.

Runnable with either `pytest tests/` or `python -m unittest discover tests`.
"""

from __future__ import annotations

import sys
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


if __name__ == "__main__":
    unittest.main()
