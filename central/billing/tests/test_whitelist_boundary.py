# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The whitelist boundary, enforced mechanically (2026-07 audit).

`@frappe.whitelist()` is authentication (a logged-in session), not authorization
(may this session act on this team). The audit found domain primitives carrying
the decorator — credit minting, payment-method mutation, invoice charging — all
reachable over `/api/method/...` by any logged-in user. security.md §3 already
forbade this; the rule was violated because it was checked by hand. This module
is that checklist line as code:

1. **Layer boundary** — `@frappe.whitelist()` may appear only in `billing/api/**`
   (plus a reviewed allowlist). Domain modules are plain Python functions.
2. **Guard on entry** — every module-level endpoint in `billing/api/**` calls the
   authz seam (or carries `pilot_credential_auth`), or sits on a reviewed
   allowlist.
3. **Regression** — the audited primitives stay rejected at the HTTP door.
"""

import ast
from pathlib import Path

import frappe
from central.billing.tests.utils import BillingTestCase

BILLING_ROOT = Path(__file__).resolve().parent.parent

# Module-level whitelisted functions allowed OUTSIDE billing/api/** — each entry
# is a reviewed exception with its reason.
BOUNDARY_ALLOWLIST = {
	"payments/webhooks.py",  # signature-first: HMAC-verified before anything runs
	"tests/e2e.py",  # hard-gated on frappe.conf.allow_tests; dead on production
}

# API endpoints allowed WITHOUT a guard token — reviewed: read-only feeds of
# non-team data, or self-scoped reads that derive everything from the session.
GUARD_ALLOWLIST = {
	"api/dashboard/account.py::whoami",  # reports the caller's own session/scope
	"api/dashboard/account.py::get_billing_geo",  # static country/state lists
	"api/dashboard/account.py::list_switchable_teams",  # session-derived team list
}

# Calling any of these on the first lines is what "guarded" means (security.md §3).
GUARD_TOKENS = (
	"require_operator",
	"require_billing_view",
	"require_billing_manage",
	"require_capability",
	"_resolve_team",
	"_require_manage",
	"_require_view",
	"_assert_owns",
)

# A decorator that authenticates + binds the team before the body runs.
AUTH_DECORATORS = {"pilot_credential_auth"}


def _decorator_name(node) -> str:
	target = node.func if isinstance(node, ast.Call) else node
	if isinstance(target, ast.Attribute):
		return target.attr
	if isinstance(target, ast.Name):
		return target.id
	return ""


def _is_whitelist_decorator(node) -> bool:
	return _decorator_name(node) == "whitelist"


def _whitelisted_functions(tree, source):
	"""(function node, inside_class, decorator names) for every whitelisted def."""
	for node in ast.walk(tree):
		if not isinstance(node, ast.ClassDef | ast.Module):
			continue
		for child in node.body:
			if not isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
				continue
			names = [_decorator_name(d) for d in child.decorator_list]
			if any(_is_whitelist_decorator(d) for d in child.decorator_list):
				yield child, isinstance(node, ast.ClassDef), names


def _billing_files():
	for path in sorted(BILLING_ROOT.rglob("*.py")):
		if "__pycache__" in path.parts:
			continue
		yield path, path.relative_to(BILLING_ROOT).as_posix()


class TestWhitelistBoundary(BillingTestCase):
	def test_no_whitelist_outside_the_api_layer(self):
		"""Domain modules never expose HTTP endpoints. A doctype controller may
		whitelist a *method* (dispatched via run_doc_method under doc permissions);
		everything else module-level must live in billing/api/** or be a reviewed
		exception."""
		violations = []
		for path, rel in _billing_files():
			source = path.read_text()
			tree = ast.parse(source)
			for fn, inside_class, _names in _whitelisted_functions(tree, source):
				if rel.startswith("api/") or rel in BOUNDARY_ALLOWLIST:
					continue
				if inside_class and rel.startswith("doctype/"):
					continue  # controller action; frappe gates it on doc permissions
				violations.append(f"{rel}::{fn.name}")
		self.assertEqual(
			violations, [],
			"@frappe.whitelist() outside billing/api/** — move the endpoint to the "
			f"API layer (do not just add a guard): {violations}",
		)

	def test_every_api_endpoint_calls_a_guard(self):
		"""Every module-level endpoint in billing/api/** authorizes on entry —
		via the authz seam, a team-resolving helper, or the pilot-credential
		decorator. New endpoints without a guard fail here, not in an audit."""
		unguarded = []
		for path, rel in _billing_files():
			if not rel.startswith("api/"):
				continue
			source = path.read_text()
			tree = ast.parse(source)
			for fn, inside_class, names in _whitelisted_functions(tree, source):
				if inside_class or f"{rel}::{fn.name}" in GUARD_ALLOWLIST:
					continue
				if AUTH_DECORATORS.intersection(names):
					continue
				body = ast.get_source_segment(source, fn) or ""
				if not any(token in body for token in GUARD_TOKENS):
					unguarded.append(f"{rel}::{fn.name}")
		self.assertEqual(
			unguarded, [],
			f"whitelisted endpoints with no authz guard on entry: {unguarded}",
		)


class TestAuditedPrimitivesStayInternal(BillingTestCase):
	"""One regression per audit exploit: the de-whitelisted primitives must be
	rejected at the HTTP door (frappe.is_whitelisted is the handler's gate)."""

	PRIMITIVES = (
		"central.billing.revenue.credits.purchase",
		"central.billing.revenue.credits.adjust_credits",
		"central.billing.revenue.credits.get_balance",
		"central.billing.revenue.credits.get_balances",
		"central.billing.payments.payments.initiate_payment_method_setup",
		"central.billing.payments.payments.confirm_payment_method",
		"central.billing.payments.payments.set_default_payment_method",
		"central.billing.payments.payments.reorder_payment_methods",
		"central.billing.payments.payments.delete_payment_method",
		"central.billing.payments.charges.pay_invoice",
		"central.billing.catalog.plans.create_configured_plan",
		"central.billing.catalog.plans.get_plan_pricing",
		"central.billing.revenue.erpnext_sync.sync_invoice",
	)

	def test_primitives_are_rejected_at_the_http_door(self):
		for dotted in self.PRIMITIVES:
			with self.subTest(method=dotted):
				with self.assertRaises(frappe.PermissionError):
					frappe.is_whitelisted(frappe.get_attr(dotted))
