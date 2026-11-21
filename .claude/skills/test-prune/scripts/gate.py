"""Fail when a test module's tests cover fewer source branches or lines after a cut.

Usage: gate.py <before .coverage> <after .coverage> <test module>
Both files need dynamic_context = test_function, and the same branch setting. Exit 1 lists what lost coverage.
"""

import sys

from redundant import load


def get_covered(path: str, module: str) -> set[tuple]:
	prefix = module + "."
	return {item for test, items in load(path).items() if test.startswith(prefix) for item in items}


def get_lost_lines(before: set, after: set) -> list[tuple]:
	return sorted(before - after)


if __name__ == "__main__":
	before = get_covered(sys.argv[1], sys.argv[3])
	after = get_covered(sys.argv[2], sys.argv[3])
	lost = get_lost_lines(before, after)

	print(f"{sys.argv[3]}: {len(before)} covered before, {len(after)} after, {len(lost)} lost")
	for item in lost[:40]:
		print(f"  {item}")
	sys.exit(1 if lost else 0)
