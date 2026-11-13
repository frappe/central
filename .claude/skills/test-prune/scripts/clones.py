"""Group test functions with the same body shape after literals are removed.

Usage: clones.py <tests-dir> [min-group-size]
A group is a merge candidate for one table-driven test.
"""

import ast
import hashlib
import sys
from collections import defaultdict
from pathlib import Path


class Shape(ast.NodeTransformer):
	def visit_Constant(self, node: ast.Constant) -> ast.AST:
		return ast.Constant(value="_")


def shape_of(function: ast.FunctionDef) -> str | None:
	body = ast.Module(body=[Shape().visit(statement) for statement in function.body], type_ignores=[])
	dumped = ast.dump(body, annotate_fields=False)
	return hashlib.sha1(dumped.encode()).hexdigest() if len(function.body) > 1 else None


def get_test_functions(root: str):
	for path in Path(root).rglob("test_*.py"):
		for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
			if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
				yield path, node


def main(root: str, minimum: int) -> None:
	groups: dict[str, list[str]] = defaultdict(list)
	for path, function in get_test_functions(root):
		key = shape_of(function)
		if key:
			groups[key].append(f"{path}:{function.lineno} {function.name}")

	found = sorted((tests for tests in groups.values() if len(tests) >= minimum), key=len, reverse=True)
	print(f"{len(found)} clone groups, {sum(len(group) for group in found)} tests\n")
	for number, tests in enumerate(found, 1):
		print(f"group {number} ({len(tests)}):")
		for test in tests:
			print(f"  {test}")


if __name__ == "__main__":
	main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 2)
