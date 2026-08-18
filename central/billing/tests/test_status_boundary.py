# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Every billing status transition goes through one authority (ADR 0016).

`states.transition()` is the only code that may write a billing status field. Assigning
`.status` / `.account_standing` directly — or through `set_value` / `db_set` — anywhere
else in `central/billing` lets a caller move a document to a state the machine forbids
(pay a cancelled invoice, skip the dunning grace step) with nothing recording it on the
Billing Event stream. This module is that rule as a test, the same mechanical guard that
keeps `@frappe.whitelist` out of the domain layer.

Setting the INITIAL state at insert is fine (a dict literal `{"status": ...}` on a new
doc); this catches later *reassignments* and `set_value`/`db_set` writes. The demo
factories and the tests construct arbitrary historical states on purpose and are out of
scope.
"""

import ast
from pathlib import Path

from central.billing.tests.utils import BillingTestCase

BILLING_ROOT = Path(__file__).resolve().parent.parent
STATE_FIELDS = {"status", "account_standing"}
MUTATORS = {"set_value", "db_set"}

# Reviewed exceptions: relative paths whose direct status writes are not billing-state
# transitions. Empty — every billing status write goes through the authority.
ALLOWLIST: set[str] = set()


def _scoped_files():
	"""Production billing modules the rule applies to (not states.py itself, not the
	demo factories or the tests, which stage historical states deliberately)."""
	for path in sorted(BILLING_ROOT.rglob("*.py")):
		parts = path.parts
		if "__pycache__" in parts or "tests" in parts or "demo" in parts:
			continue
		rel = path.relative_to(BILLING_ROOT).as_posix()
		if rel == "states.py" or rel in ALLOWLIST:
			continue
		yield path, rel


def _mutator_touches_state(call: ast.Call) -> bool:
	"""A set_value/db_set that writes a state field, positionally ("status", …) or via a
	dict payload ({"status": …})."""
	for arg in call.args:
		if isinstance(arg, ast.Constant) and arg.value in STATE_FIELDS:
			return True
		if isinstance(arg, ast.Dict) and any(
			isinstance(k, ast.Constant) and k.value in STATE_FIELDS for k in arg.keys
		):
			return True
	return False


def _direct_state_writes(tree: ast.AST) -> list[int]:
	"""Line numbers where a billing status field is written directly (not via transition)."""
	hits = []
	for node in ast.walk(tree):
		targets = (
			node.targets
			if isinstance(node, ast.Assign)
			else [node.target]
			if isinstance(node, ast.AugAssign)
			else []
		)
		if any(isinstance(t, ast.Attribute) and t.attr in STATE_FIELDS for t in targets):
			hits.append(node.lineno)
		if (
			isinstance(node, ast.Call)
			and isinstance(node.func, ast.Attribute)
			and node.func.attr in MUTATORS
			and _mutator_touches_state(node)
		):
			hits.append(node.lineno)
	return hits


class TestStatusTransitionBoundary(BillingTestCase):
	def test_no_direct_status_writes_outside_the_authority(self):
		violations = []
		for path, rel in _scoped_files():
			for lineno in _direct_state_writes(ast.parse(path.read_text())):
				violations.append(f"{rel}:{lineno}")
		self.assertEqual(
			violations,
			[],
			"billing status written outside states.py — route it through "
			f"central.billing.states.transition(): {violations}",
		)

	def test_the_guard_actually_catches_a_violation(self):
		# Guard against the guard silently passing: a planted direct write must be caught,
		# both the attribute-assignment form and the set_value form.
		planted = ast.parse(
			'inv.status = "Paid"\n'
			'frappe.db.set_value("Subscription", n, "account_standing", "Current")\n'
			'frappe.db.set_value("Invoice", n, {"status": "Open"})\n'
		)
		self.assertEqual(len(_direct_state_writes(planted)), 3)
