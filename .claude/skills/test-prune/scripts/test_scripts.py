"""Assert-based check of the analysis logic. Usage: python3 test_scripts.py"""

import ast

from clones import shape_of
from redundant import analyse, greedy_cover

a, b, c = ("f.py", 1), ("f.py", 2), ("f.py", 3)
tests = {
	"app.tests.test_x.TestX.test_small": frozenset({a}),
	"app.tests.test_x.TestX.test_wide": frozenset({a, b}),
	"app.tests.test_x.TestX.test_denied_for_other_team": frozenset({b}),
	"app.tests.test_x.TestX.test_other": frozenset({c}),
}

assert set(greedy_cover(tests)) == {"app.tests.test_x.TestX.test_wide", "app.tests.test_x.TestX.test_other"}

[row] = analyse(tests)
found = {item["test"].rsplit(".", 1)[-1]: item for item in row["subsets"]}
assert set(found) == {"test_small", "test_denied_for_other_team"}
assert found["test_small"]["subset_of"].endswith("test_wide")
assert found["test_denied_for_other_team"]["protected_name"] is True
assert found["test_small"]["protected_name"] is False


def function(source: str) -> ast.FunctionDef:
	return ast.parse(source).body[0]


same_a = function("def test_a():\n    x = make(1)\n    assert x.total == 10\n")
same_b = function("def test_b():\n    x = make(2)\n    assert x.total == 20\n")
other = function("def test_c():\n    x = build(2)\n    assert x.total == 20\n")
assert shape_of(same_a) == shape_of(same_b)
assert shape_of(same_a) != shape_of(other)

from datetime import datetime, timedelta

from slow import class_seconds

start = datetime(2026, 1, 1)
stamps = [
	(start, "app.tests.test_x.TestX"),
	(start + timedelta(seconds=4), "Starting tests for app: app, category: integration"),
	(start + timedelta(seconds=5), "app.tests.test_y.TestY"),
	(start + timedelta(seconds=7), "done"),
]
assert class_seconds(stamps) == {"app.tests.test_x.TestX": 4.0, "app.tests.test_y.TestY": 2.0}

from gate import get_lost_lines

assert get_lost_lines({a, b}, {a, b, c}) == []
assert get_lost_lines({a, b}, {a}) == [b]

print("test_scripts ok")
