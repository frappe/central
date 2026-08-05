# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Retry / dunning + staged suspension (issue #14)."""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from central.billing import settings
from central.billing.catalog import subscriptions
from central.billing.catalog.signing import generate_keypair
from central.billing.gateways.base import PaymentResult
from central.billing.revenue import dunning
from central.billing.tests.test_stripe_adapter import make_stripe_gateway
from central.billing.tests.utils import (
	billing_settings,
	ensure_atlas_instance,
	ensure_team,
	make_plan,
	set_team_tier,
)

TEAM = "team-dunning"
CLUSTER = "ap-south-1"
PLAN = "bundle-dunning-test"
GATEWAY = "GW-Test-Stripe"
DUE = "2026-06-01"


@contextmanager
def declining_gateway():
	adapter = MagicMock()
	adapter.charge.return_value = PaymentResult(
		success=False, status="Failed", failure_code="card_declined", failure_reason="Card declined"
	)
	with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
		yield adapter


def day(n):
	return frappe.utils.add_days(DUE, n)


class DunningTestBase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		ensure_atlas_instance(CLUSTER)
		make_plan(PLAN)
		make_stripe_gateway(GATEWAY)
		self._priv, self._pub = generate_keypair()
		frappe.conf.entitlement_private_key = self._priv
		self._purge()
		set_team_tier(TEAM, level="t1", max_spend=50000)

	def tearDown(self):
		self._purge()

	def _purge(self):
		for dt in ("Invoice", "Payment Attempt"):
			frappe.db.delete(dt, {"team": TEAM})
		for pm in frappe.get_all("Payment Method", {"team": TEAM}, pluck="name"):
			frappe.db.delete("Payment Method", {"name": pm})
		frappe.db.delete("Entitlement Token", {"team": TEAM})
		frappe.db.delete("Billing Profile", {"team": TEAM})
		for sub in frappe.get_all("Subscription", {"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": sub})
			frappe.db.delete("Subscription", {"name": sub})
		frappe.db.commit()

	def _card(self):
		return (
			frappe.get_doc(
				{
					"doctype": "Payment Method",
					"team": TEAM,
					"gateway": GATEWAY,
					"method_type": "Card",
					"status": "Active",
					"gateway_method_id": "pm_x",
					"gateway_customer_id": "cus_x",
					"is_default": 1,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _subscription(self, with_card=True):
		return subscriptions.create_subscription(
			team=TEAM,
			cluster=CLUSTER,
			plan=PLAN,
			billing_cycle="Monthly",
			default_payment_method=self._card() if with_card else None,
			gateway=GATEWAY if with_card else None,
		).name

	def _open_invoice(self, sub, total=1000):
		return (
			frappe.get_doc(
				{
					"doctype": "Invoice",
					"team": TEAM,
					"subscription": sub,
					"invoice_type": "Billable",
					"status": "Open",
					"period_start": "2026-05-01",
					"period_end": "2026-05-31",
					"currency": "INR",
					"subtotal": total,
					"total": total,
					"expected_collection": total,
					"due_date": DUE,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _attempts(self, inv):
		return frappe.db.count("Payment Attempt", {"invoice": inv})

	def _standing(self, sub):
		return frappe.db.get_value("Subscription", sub, "account_standing")

	def _has_directive(self, field):
		name = frappe.db.get_value("Entitlement Token", {"team": TEAM}, "name", order_by="creation desc")
		return bool(name and frappe.db.get_value("Entitlement Token", name, field))


class TestRetrySchedule(DunningTestBase):
	def test_failed_method_is_not_retried_on_later_days(self):
		"""Escalate, don't repeat (#28): a method that failed once is never retried.
		With a single card the Day 1 attempt is the only charge; Day 3/7 escalate."""
		sub = self._subscription()
		inv = self._open_invoice(sub)
		with declining_gateway():
			dunning.process_invoice_dunning(inv, now=day(1))
			self.assertEqual(self._attempts(inv), 1)
			dunning.process_invoice_dunning(inv, now=day(3))
			self.assertEqual(self._attempts(inv), 1)  # not repeated
			dunning.process_invoice_dunning(inv, now=day(7))
			self.assertEqual(self._attempts(inv), 1)

		notes = frappe.get_all(
			"Comment",
			{"reference_doctype": "Invoice", "reference_name": inv, "comment_type": "Info"},
			pluck="content",
		)
		self.assertEqual(sum("retry" in n for n in notes), 1)

	def test_backup_method_is_tried_once(self):
		"""A backup is charged after the primary fails, then neither is retried."""
		sub = self._subscription()  # primary card pm_x (priority 0)
		frappe.get_doc(
			{
				"doctype": "Payment Method",
				"team": TEAM,
				"gateway": GATEWAY,
				"method_type": "Card",
				"status": "Active",
				"gateway_method_id": "pm_y",
				"gateway_customer_id": "cus_x",
				"priority": 1,
			}
		).insert(ignore_permissions=True)
		inv = self._open_invoice(sub)
		with declining_gateway():
			dunning.process_invoice_dunning(inv, now=day(1))
			self.assertEqual(self._attempts(inv), 2)  # primary then backup, one each
			dunning.process_invoice_dunning(inv, now=day(3))
			self.assertEqual(self._attempts(inv), 2)  # both exhausted, no repeat

	def test_same_day_rerun_does_not_double_retry(self):
		sub = self._subscription()
		inv = self._open_invoice(sub)
		with declining_gateway():
			dunning.process_invoice_dunning(inv, now=day(1))
			dunning.process_invoice_dunning(inv, now=day(1))  # idempotent
		self.assertEqual(self._attempts(inv), 1)


class TestStagedEscalation(DunningTestBase):
	def _run_through(self, inv, sub, last_day):
		with declining_gateway():
			for d in (1, 3, 7, 14, 44):
				if d <= last_day:
					dunning.process_invoice_dunning(inv, now=day(d))

	def test_day7_overdue_pastdue_still_running(self):
		sub = self._subscription()
		inv = self._open_invoice(sub)
		self._run_through(inv, sub, last_day=7)

		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Overdue")
		self.assertEqual(self._standing(sub), "Past Due")  # grace
		self.assertFalse(self._has_directive("suspend"))  # not stopped — still running

	def test_day14_suspend_directive_on_token_channel(self):
		sub = self._subscription()
		inv = self._open_invoice(sub)
		self._run_through(inv, sub, last_day=14)

		self.assertEqual(self._standing(sub), "Suspended")
		self.assertTrue(self._has_directive("suspend"))  # cap-0 + suspend rides the token

	def test_day44_terminate_directive(self):
		sub = self._subscription()
		inv = self._open_invoice(sub)
		self._run_through(inv, sub, last_day=44)

		self.assertTrue(self._has_directive("terminate"))

	def test_the_ladder_follows_billing_settings(self):
		"""A shortened ladder escalates on its own days, not the shipped ones."""
		sub = self._subscription()
		inv = self._open_invoice(sub)
		with billing_settings(dunning_retry_days="1, 2", suspend_after_days=4, terminate_after_days=6):
			with declining_gateway():
				for d in (1, 2, 4, 6):
					dunning.process_invoice_dunning(inv, now=day(d))

		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Overdue")
		self.assertTrue(self._has_directive("suspend"))
		self.assertTrue(self._has_directive("terminate"))

	def test_cost_report_invoice_is_not_dunned(self):
		sub = self._subscription()
		inv = self._open_invoice(sub)
		frappe.db.set_value("Invoice", inv, "invoice_type", "Cost Report")
		out = dunning.process_invoice_dunning(inv, now=day(14))
		self.assertEqual(out["skipped"], "Cost Report")
		self.assertEqual(self._attempts(inv), 0)


class TestCreditsOnlyDunning(DunningTestBase):
	def test_credits_only_escalates_without_retries(self):
		sub = self._subscription(with_card=False)  # no card → no charge retries
		inv = self._open_invoice(sub)
		for d in (7, 14):
			dunning.process_invoice_dunning(inv, now=day(d))

		self.assertEqual(self._attempts(inv), 0)  # nothing to retry against
		self.assertEqual(self._standing(sub), "Suspended")  # but still escalates


class TestOurDelayIsNotTheirDelinquency(DunningTestBase):
	"""A backlogged billing run must not cost the customer their grace period.

	Every dunning stage is counted from a date that assumes we asked for the money
	when we said we would. When the run is late, rate-limited, or broken, that
	assumption is false — and starting the retry ladder, the Overdue notice and the
	suspension countdown anyway would charge the customer for our outage.
	"""

	def test_a_gateway_that_rate_limits_us_defers_the_ladder(self):
		sub = self._subscription()
		inv = self._open_invoice(sub)

		# Day 7 with no deferral: the invoice would go Overdue and the team past_due.
		# The rate limit lands first, so the same day must do nothing instead.
		dunning.defer_dunning(inv, "429 from the gateway")
		result = dunning.process_invoice_dunning(inv, now=day(7))

		self.assertEqual(result["action"], "none")
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Open")
		self.assertNotEqual(self._standing(sub), "Past Due")

	def test_the_deferred_ladder_still_runs_from_the_fair_date(self):
		sub = self._subscription()
		inv = self._open_invoice(sub)
		dunning.defer_dunning(inv, "the run backed up")

		# Deferral is grace, not amnesty: a week after the date we could actually
		# have asked on, the ladder escalates exactly as it always would.
		fair = frappe.db.get_value("Invoice", inv, "dunning_starts_on")
		self.assertEqual(
			fair,
			frappe.utils.getdate(frappe.utils.add_days(frappe.utils.nowdate(), settings.invoice_due_days())),
		)
		with declining_gateway():
			dunning.process_invoice_dunning(inv, now=frappe.utils.add_days(fair, 7))
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Overdue")

	def test_deferral_only_ever_moves_forward(self):
		# Day 2 of a three-day backlog must not hand back the grace day 1 granted,
		# and a stale failure arriving late must not rewind an already-fair clock.
		sub = self._subscription()
		inv = self._open_invoice(sub)
		dunning.defer_dunning(inv, "first failure")
		granted = frappe.db.get_value("Invoice", inv, "dunning_starts_on")

		self.assertFalse(dunning.defer_dunning(inv, "same day, second failure"))
		self.assertEqual(frappe.db.get_value("Invoice", inv, "dunning_starts_on"), granted)

	def test_an_invoice_that_collected_normally_keeps_the_due_date_clock(self):
		# The fairness rule must not slow down dunning for everyone else.
		sub = self._subscription()
		inv = self._open_invoice(sub)
		frappe.db.set_value("Invoice", inv, "dunning_starts_on", DUE)

		with declining_gateway():
			result = dunning.process_invoice_dunning(inv, now=day(7))
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Overdue")
		self.assertEqual(result["days_overdue"], 7)

	def test_deferring_never_touches_the_due_date(self):
		# What the customer owed and when is an accounting fact; AR aging keeps
		# reading it. Only the escalation clock moves.
		sub = self._subscription()
		inv = self._open_invoice(sub)
		dunning.defer_dunning(inv, "the run backed up")
		self.assertEqual(str(frappe.db.get_value("Invoice", inv, "due_date")), DUE)
