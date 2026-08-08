# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Nothing in the projection package is reachable only from its own tests.

A module with green tests and no callers reads as finished in every report and does
nothing for anybody. This is the guard that would have caught it.
"""

import ast
from pathlib import Path

import frappe

from central.billing.tests.utils import BillingTestCase as IntegrationTestCase

ROOT = Path(frappe.get_app_path("central")) / "billing"
PACKAGE = ROOT / "projection"

# Entry points: reached over HTTP, by the scheduler, or by a report rather than by
# another module.
ENTRY_POINTS = {"api.py"}


def _module_names() -> list[str]:
	return sorted(p.stem for p in PACKAGE.glob("*.py") if p.name not in ("__init__.py", *ENTRY_POINTS))


def _imports_in(path: Path) -> set[str]:
	found: set[str] = set()
	tree = ast.parse(path.read_text())
	for node in ast.walk(tree):
		if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("billing.projection"):
			found |= {alias.name for alias in node.names}
		elif isinstance(node, ast.ImportFrom) and "billing.projection." in (node.module or ""):
			found.add((node.module or "").rsplit(".", 1)[-1])
	return found


def _production_files():
	for path in sorted(ROOT.rglob("*.py")):
		parts = path.parts
		if "__pycache__" in parts or "tests" in parts:
			continue
		yield path


class TestEverythingIsReachable(IntegrationTestCase):
	def test_no_projection_module_is_dead_code(self):
		used: set[str] = set()
		for path in _production_files():
			if path.parent == PACKAGE and path.stem not in ENTRY_POINTS:
				# A module importing itself proves nothing.
				used |= _imports_in(path) - {path.stem}
			else:
				used |= _imports_in(path)

		unreachable = [m for m in _module_names() if m not in used]
		self.assertEqual(
			unreachable,
			[],
			f"these have tests but nothing calls them, which reads as finished and is not: {unreachable}",
		)
