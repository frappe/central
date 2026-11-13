"""Find tests whose covered branches are a subset of another test's, per test module.

Usage: redundant.py <.coverage> [--json out.json]
Needs a coverage file recorded with dynamic_context = test_function, best with branch = True.
Without branch data it falls back to lines, which also matches tests that take opposite branches.
A subset is a candidate, not a verdict: check assertions with references/rubric.md.
"""

import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

from coverage.numbits import numbits_to_nums

PROTECTED = re.compile(
	r"den(y|ied)|forbid|cross|other_team|another_team|permission|unauthori|cannot|can_not|not_allowed|"
	r"reject|refuse|block|regression|leak|security|tenant|idempot|replay|retry|twice|duplicate",
	re.IGNORECASE,
)


ARCS = """select context.context, file.path, arc.fromno, arc.tono from arc
	join context on context.id = arc.context_id join file on file.id = arc.file_id where context.context != ''"""
LINES = """select context.context, file.path, line_bits.numbits from line_bits
	join context on context.id = line_bits.context_id join file on file.id = line_bits.file_id
	where context.context != ''"""


def load(path: str) -> dict[str, frozenset[tuple]]:
	"""Per test: the (file, from, to) branches it ran, or (file, line) when no branches were recorded."""
	database = sqlite3.connect(path)
	covered: dict[str, set[tuple]] = defaultdict(set)

	for test, source, start, end in database.execute(ARCS):
		covered[test].add((source, start, end))

	if not covered:
		for test, source, bits in database.execute(LINES):
			covered[test].update((source, line) for line in numbits_to_nums(bits))

	return {test: frozenset(items) for test, items in covered.items()}


def module_of(test: str) -> str:
	return test.rsplit(".", 2)[0]


def greedy_cover(tests: dict[str, frozenset]) -> list[str]:
	"""Smallest-ish set of tests that keeps every line the group covers."""
	left = set().union(*tests.values())
	keep: list[str] = []

	while left:
		best = max(tests, key=lambda test: len(tests[test] & left))
		keep.append(best)
		left -= tests[best]

	return keep


def analyse(tests: dict[str, frozenset]) -> list[dict]:
	by_module: dict[str, dict[str, frozenset]] = defaultdict(dict)
	for test, covered in tests.items():
		by_module[module_of(test)][test] = covered

	report = []
	for module, group in sorted(by_module.items()):
		subsets = []
		for test, covered in group.items():
			wider = [other for other, lines in group.items() if other != test and covered <= lines]
			if wider:
				subsets.append(
					{
						"test": test,
						"subset_of": min(wider, key=lambda other: len(group[other])),
						"protected_name": bool(PROTECTED.search(test.rsplit(".", 1)[-1])),
					}
				)
		keep = greedy_cover(group)
		report.append({"module": module, "tests": len(group), "cover_keeps": len(keep), "subsets": subsets})

	return report


def main(argv: list[str]) -> None:
	report = analyse(load(argv[1]))

	if "--json" in argv:
		Path(argv[argv.index("--json") + 1]).write_text(json.dumps(report, indent=1))

	print_report(report)


def print_report(report: list[dict]) -> None:
	total = sum(row["tests"] for row in report)
	candidates = sum(1 for row in report for item in row["subsets"] if not item["protected_name"])
	print(f"{total} tests with a context, {candidates} unprotected subset candidates\n")
	for row in sorted(report, key=lambda row: -len(row["subsets"])):
		if row["subsets"]:
			print_module(row)


def print_module(row: dict) -> None:
	print(
		f"{row['module']}: {row['tests']} tests, cover needs {row['cover_keeps']}, {len(row['subsets'])} subsets"
	)
	for item in row["subsets"]:
		flag = "  [protected name]" if item["protected_name"] else ""
		test = ".".join(item["test"].rsplit(".", 2)[-2:])
		print(f"  {test} <= {item['subset_of'].rsplit('.', 1)[-1]}{flag}")


if __name__ == "__main__":
	main(sys.argv)
