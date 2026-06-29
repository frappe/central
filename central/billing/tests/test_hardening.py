# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Security + load hardening — proving v1's failure classes are closed (issue #22)."""

import os
import re
import threading
from contextlib import contextmanager
from unittest.mock import patch

import frappe
import stripe
from frappe.tests import IntegrationTestCase

from central import billing
from central.billing import authz
from central.billing.tests.utils import make_billing_team, make_custom_role_team, make_user
from central.billing.tests.test_stripe_adapter import make_stripe_gateway
from central.billing.payments.webhooks import process_webhook

FLOOD_EVENT = "evt_flood_1"
FLOOD_PAYLOAD = (
	b'{"id":"' + FLOOD_EVENT.encode() + b'","type":"payment_intent.succeeded",'
	b'"data":{"object":{"id":"pi_flood"}}}'
)


def run_threads(n, fn):
	site = frappe.local.site
	results = {}

	def worker(i):
		frappe.init(site=site)
		frappe.connect()
		frappe.set_user("Administrator")
		try:
			fn(i)
			frappe.db.commit()
			results[i] = "ok"
		except Exception as e:  # noqa: BLE001
			frappe.db.rollback()
			results[i] = type(e).__name__
		finally:
			frappe.destroy()

	threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
	for t in threads:
		t.start()
	for t in threads:
		t.join()
	return results


# --- permission enforcement (Agent key can't hit customer/admin) -------------


class TestPermissionGuards(IntegrationTestCase):
	"""Authorisation is Central's capability IAM (ADR 0004): no billing roles of
	our own. The cluster Agent key holds no billing capability and is not an
	operator, so it is denied every customer/admin endpoint."""

	def setUp(self):
		# A unique user per test — grants must not leak across tests.
		self.user = make_user(f"hardening-{frappe.generate_hash(6)}@example.com")

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_non_operator_is_denied_admin_endpoint(self):
		# A user with no operator bypass (stands in for the Agent API key) → 403.
		frappe.set_user(self.user)
		with self.assertRaises(frappe.PermissionError):
			authz.require_operator()

	def test_operator_is_allowed(self):
		frappe.get_doc("User", self.user).add_roles("System Manager")
		frappe.set_user(self.user)
		authz.require_operator()  # no raise

	def test_team_scoping_rejects_other_team(self):
		team = make_billing_team(self.user)  # Billing role → billing:view
		frappe.set_user(self.user)
		authz.require_billing_view(team.name)  # own team ok
		with self.assertRaises(frappe.PermissionError):
			authz.require_billing_view("team-other")  # never silently widened

	def test_member_without_capability_is_denied(self):
		# A team member whose role carries no billing capability → 403.
		team = make_billing_team(self.user, role="Viewer")
		frappe.set_user(self.user)
		with self.assertRaises(frappe.PermissionError):
			authz.require_billing_view(team.name)

	def test_view_only_capability_gates_manage(self):
		# A custom role granting billing:view WITHOUT billing:manage: the view gate
		# passes, the manage gate is denied — the split the system roles don't have.
		team = make_custom_role_team(self.user, ["billing:view"])
		frappe.set_user(self.user)
		authz.require_billing_view(team.name)  # view ok
		with self.assertRaises(frappe.PermissionError):
			authz.require_billing_manage(team.name)  # manage denied


# --- no raw SQL string interpolation -----------------------------------------


class TestNoSqlInjection(IntegrationTestCase):
	def test_no_fstring_or_format_in_db_sql(self):
		app_dir = os.path.dirname(billing.__file__)
		offenders = []
		# Flag an f-string/format/%-interpolated string handed to frappe.db.sql.
		pattern = re.compile(r"db\.sql\(\s*(f[\"']|.*\.format\(|.*%\s*\()")
		for root, _dirs, files in os.walk(app_dir):
			for f in files:
				if not f.endswith(".py"):
					continue
				path = os.path.join(root, f)
				with open(path, encoding="utf-8") as fh:
					for n, line in enumerate(fh, 1):
						if pattern.search(line):
							offenders.append(f"{path}:{n}: {line.strip()}")
		self.assertEqual(offenders, [], f"raw SQL interpolation found:\n" + "\n".join(offenders))


# --- webhook replay + concurrent flood ---------------------------------------


@contextmanager
def valid_signature():
	with patch.object(stripe.Webhook, "construct_event", return_value={"id": FLOOD_EVENT}):
		yield


class TestWebhookHardening(IntegrationTestCase):
	def setUp(self):
		make_stripe_gateway()
		frappe.db.delete("Webhook Event", {"gateway_event_id": FLOOD_EVENT})
		frappe.db.commit()

	def tearDown(self):
		frappe.db.delete("Webhook Event", {"gateway_event_id": FLOOD_EVENT})
		frappe.db.commit()

	def _count(self):
		return frappe.db.count("Webhook Event", {"gateway_event_id": FLOOD_EVENT})

	def test_replay_is_idempotent_no_second_job(self):
		with valid_signature(), patch("frappe.enqueue") as enqueue:
			process_webhook("Stripe", FLOOD_PAYLOAD, dict({"Stripe-Signature": "x"}))
			process_webhook("Stripe", FLOOD_PAYLOAD, dict({"Stripe-Signature": "x"}))  # replay
		self.assertEqual(self._count(), 1)  # one row
		self.assertEqual(enqueue.call_count, 1)  # one job — replay had no side effect

	def test_concurrent_flood_stores_exactly_one(self):
		def deliver(_i):
			with patch.object(stripe.Webhook, "construct_event", return_value={"id": FLOOD_EVENT}):
				process_webhook("Stripe", FLOOD_PAYLOAD, {"Stripe-Signature": "x"})

		run_threads(10, deliver)  # 10 simultaneous deliveries of the same event
		frappe.db.rollback()
		self.assertEqual(self._count(), 1)  # dedupe held under contention


# --- load: scaled two-phase invoice run --------------------------------------


class TestLoadTwoPhase(IntegrationTestCase):
	N = 100
	CLUSTER = "ap-south-1"
	PLAN = "bundle-load-test"

	def setUp(self):
		from central.billing.tests.utils import ensure_team, make_plan

		make_plan(self.PLAN)
		self._teams = [f"team-load-{i}" for i in range(self.N)]
		for team in self._teams:
			ensure_team(team)
		self._purge()

	def tearDown(self):
		self._purge()

	def _purge(self):
		for team in self._teams:
			frappe.db.delete("Invoice", {"team": team})
			frappe.db.delete("Price Lock", {"team": team})
			for sub in frappe.get_all("Subscription", {"team": team}, pluck="name"):
				frappe.db.delete("Subscription Change", {"subscription": sub})
				frappe.db.delete("Subscription", {"name": sub})
		frappe.db.commit()

	def test_thousand_scale_run_no_double_processing(self):
		from central.billing.revenue import invoicing
		from central.billing.tests.utils import add_segment, make_billing_subscription

		for team in self._teams:
			sub = make_billing_subscription(team, self.CLUSTER, self.PLAN, billing_cycle="Monthly")
			add_segment(sub, "Created", 1000, "2026-06-01 00:00:00")

		drafts = invoicing.generate_draft_invoices("2026-06-01", "2026-06-30")
		mine = [d for d in drafts if frappe.db.get_value("Invoice", d, "team") in self._teams]
		self.assertEqual(len(mine), self.N)  # one draft per subscription

		# Re-running phase 1 must not create a second invoice per (sub, period).
		invoicing.generate_draft_invoices("2026-06-01", "2026-06-30")
		for team in self._teams:
			self.assertEqual(frappe.db.count("Invoice", {"team": team}), 1)

		# Phase 2 opens each exactly once.
		invoicing.open_drafts("2026-06-30")
		opened = sum(1 for d in mine if frappe.db.get_value("Invoice", d, "status") == "Open")
		self.assertEqual(opened, self.N)
