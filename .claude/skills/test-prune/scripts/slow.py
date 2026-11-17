"""Rank slow test classes and modules from frappe.testing.log. Usage: slow.py <log> [top]

The runner logs a timestamp when each test class starts, so a class's time is the gap to the next
stamp. It includes setUpClass and fixtures, which is where most of the cost usually sits.
"""

import re
import sys
from collections import defaultdict
from datetime import datetime
from itertools import pairwise
from pathlib import Path

STAMP = re.compile(r"^(?P<at>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+) \w+ frappe\.testing (?P<what>.+)$")
TEST_CLASS = re.compile(r"^[\w.]+\.Test\w*$")


def read_stamps(log_path: str) -> list[tuple[datetime, str]]:
	stamps = []
	for line in Path(log_path).read_text(encoding="utf-8").splitlines():
		match = STAMP.match(line.rstrip("\n"))
		if match:
			stamps.append((datetime.strptime(match["at"], "%Y-%m-%d %H:%M:%S,%f"), match["what"]))
	return stamps


def class_seconds(stamps: list[tuple[datetime, str]]) -> dict[str, float]:
	seconds: dict[str, float] = defaultdict(float)
	for (started, what), (ended, _) in pairwise(stamps):
		if TEST_CLASS.match(what):
			seconds[what] += (ended - started).total_seconds()
	return seconds


def main(log_path: str, top: int) -> None:
	classes = class_seconds(read_stamps(log_path))
	modules: dict[str, float] = defaultdict(float)
	for name, seconds in classes.items():
		modules[name.rsplit(".", 1)[0]] += seconds

	print(f"{len(classes)} test classes, {sum(classes.values()):.0f}s total\n")
	print("slowest modules:")
	for module, seconds in sorted(modules.items(), key=lambda item: -item[1])[:top]:
		print(f"  {seconds:7.1f}s  {module}")
	print("\nslowest classes:")
	for name, seconds in sorted(classes.items(), key=lambda item: -item[1])[:top]:
		print(f"  {seconds:7.1f}s  {name}")


if __name__ == "__main__":
	main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 25)
