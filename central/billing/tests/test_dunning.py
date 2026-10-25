# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Retry / dunning + staged suspension (issue #14)."""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from central.billing import settings
from central.billing.catalog import subscriptions
from central.billing.gateways.base import PaymentResult
from central.billing.payments import decline
from central.billing.revenue import dunning
from central.billing.tests.test_stripe_adapter import make_stripe_gateway
from central.billing.tests.utils import (
	BillingTestCase,
	billing_settings,
	ensure_atlas_instance,
	ensure_team,
	make_plan,
	set_team_tier,
)

TEAM = "team-dunning"
CLUSTER = "ap-south-1"
PLAN = "bundle-dunning-test"
GATEWAY = "Stripe"
DUE = "2026-06-01"


@contextmanager
def declining_gateway(failure_code="card_declined", decline_code=None):
	adapter = MagicMock()
	adapter.prepare_charge.return_value = None  # Stripe-like: no order to store
	adapter.charge.return_value = PaymentResult(
		success=False,
		status="Failed",
		failure_code=failure_code,
		decline_code=decline_code,
		failure_reason="Card declined",
	)
	with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
		yield adapter


def day(n):
	return frappe.utils.add_days(DUE, n)


class DunningTestBase(BillingTestCase):
	def setUp(self):
		ensure_team(TEAM)
		ensure_atlas_instance(CLUSTER)
		make_plan(PLAN)
		make_stripe_gateway()
		set_team_tier(TEAM, level="t1", max_spend=50000)

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


class TestRetrySchedule(DunningTestBase):
	"""Each retry day is a new collection round: a card whose decline can clear is
	charged again, once per round. A hard decline is never charged again."""

	def _dun(self, inv, n):
		with self.freeze_time(f"{day(n)} 03:00:00"):
			dunning.process_invoice_dunning(inv, now=day(n))

	def test_a_declined_card_is_retried_on_each_retry_day(self):
		inv = self._open_invoice(self._subscription())
		with declining_gateway(decline_code="insufficient_funds"):
			for n, attempts in ((1, 1), (2, 1), (3, 2), (7, 3)):
				self._dun(inv, n)
				self.assertEqual(self._attempts(inv), attempts, f"day {n}")

	def test_a_hard_decline_is_not_retried(self):
		inv = self._open_invoice(self._subscription())
		with declining_gateway(decline_code="stolen_card"):
			self._dun(inv, 1)
			self._dun(inv, 3)
			self._dun(inv, 7)
		self.assertEqual(self._attempts(inv), 1)

	def test_an_expired_card_is_not_retried(self):
		inv = self._open_invoice(self._subscription())
		with declining_gateway(failure_code="expired_card"):
			self._dun(inv, 1)
			self._dun(inv, 3)
		self.assertEqual(self._attempts(inv), 1)

	def test_each_round_tries_the_primary_then_the_backup_once(self):
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
			self._dun(inv, 1)
			self.assertEqual(self._attempts(inv), 2)
			self._dun(inv, 3)
			self.assertEqual(self._attempts(inv), 4)

	def test_a_round_charges_a_card_once_whatever_the_clock_says(self):
		inv = self._open_invoice(self._subscription())
		with declining_gateway(decline_code="insufficient_funds"):
			dunning.process_invoice_dunning(inv, now="2030-01-01")
		self.assertEqual(self._attempts(inv), 1)

	def test_same_day_rerun_does_not_double_retry(self):
		inv = self._open_invoice(self._subscription())
		with declining_gateway():
			self._dun(inv, 1)
			self._dun(inv, 1)
		self.assertEqual(self._attempts(inv), 1)


class TestStagedEscalation(DunningTestBase):
	def _run_through(self, inv, sub, last_day):
		with declining_gateway():
			for d in (1, 3, 7, 14, 44):
				if d <= last_day:
					dunning.process_invoice_dunning(inv, now=day(d))

	def _running(self, sub):
		server = frappe.db.get_value("Subscription", sub, "server_id")
		frappe.db.set_value("Virtual Machine", server, {"status": "Running", "atlas_vm_id": "vm-dunning"})
		return server

	def test_day7_overdue_pastdue_still_running(self):
		sub = self._subscription()
		self._running(sub)
		inv = self._open_invoice(sub)
		with patch("central.resource_actions.submit_billing_command") as stop:
			self._run_through(inv, sub, last_day=7)

		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Overdue")
		self.assertEqual(self._standing(sub), "Past Due")  # grace
		stop.assert_not_called()  # late is not yet cut off

	def test_day14_suspend_stops_running_servers(self):
		sub = self._subscription()
		server = self._running(sub)
		inv = self._open_invoice(sub)
		with patch("central.resource_actions.submit_billing_command") as stop:
			self._run_through(inv, sub, last_day=14)

		self.assertEqual(self._standing(sub), "Suspended")
		stop.assert_called_once_with("stop", server)
		self.assertTrue(frappe.db.get_value("Subscription", sub, "stopped_for_nonpayment"))

	def test_a_server_that_will_not_stop_stays_flagged_for_operators(self):
		from central.billing.platform import alerts

		sub = self._subscription()
		self._running(sub)
		inv = self._open_invoice(sub)
		with patch(
			"central.resource_actions.submit_billing_command",
			side_effect=frappe.ValidationError("region down"),
		):
			self._run_through(inv, sub, last_day=14)

		self.assertEqual(self._standing(sub), "Suspended")
		self.assertFalse(frappe.db.get_value("Subscription", sub, "stopped_for_nonpayment"))
		self.assertIn(sub, [a["subject"] for a in alerts.suspended_servers_running()])

	def test_a_subscription_that_cannot_suspend_is_logged_not_raised(self):
		sub = self._subscription()
		real = subscriptions.set_standing

		def refuse_this_one(name, standing, **kwargs):
			if name == sub:
				raise subscriptions.InvalidTransition("unexpected standing")
			return real(name, standing, **kwargs)

		with (
			patch.object(subscriptions, "set_standing", side_effect=refuse_this_one),
			patch("frappe.log_error") as logged,
		):
			suspended = subscriptions.suspend_for_nonpayment(TEAM)

		self.assertNotIn(sub, suspended)
		self.assertEqual(logged.call_args.kwargs["reference_name"], sub)

	def test_day44_termination_is_due_and_nothing_is_deleted(self):
		from central.billing.platform import alerts

		sub = self._subscription()
		inv = self._open_invoice(sub)
		with (
			patch("central.resource_actions.submit_billing_command"),
			patch("central.api.servers.terminate_server") as end,
		):
			self._run_through(inv, sub, last_day=44)
			out = dunning.process_invoice_dunning(inv, now=day(44))

		self.assertIn("termination_due", out["actions"])
		end.assert_not_called()
		with patch("frappe.utils.nowdate", return_value=day(44)):
			self.assertIn(inv, [a["subject"] for a in alerts.termination_due()])

	def test_paying_restores_the_team_and_starts_what_dunning_stopped(self):
		from central.billing.states import transition

		sub = self._subscription()
		server = self._running(sub)
		inv = self._open_invoice(sub)
		with patch("central.resource_actions.submit_billing_command"):
			self._run_through(inv, sub, last_day=14)
		frappe.db.set_value("Virtual Machine", server, "status", "Stopped")

		doc = frappe.get_doc("Invoice", inv)
		transition(doc, "Paid", reason="test payment", actor="test")
		with patch("central.resource_actions.submit_billing_command") as start:
			doc.save(ignore_permissions=True)

		self.assertEqual(self._standing(sub), "Current")
		start.assert_called_once_with("start", server)
		self.assertFalse(frappe.db.get_value("Subscription", sub, "stopped_for_nonpayment"))

	def test_cancelling_an_unpaid_invoice_does_not_restore_the_team(self):
		from central.billing.states import transition

		sub = self._subscription()
		self._running(sub)
		inv = self._open_invoice(sub)
		with patch("central.resource_actions.submit_billing_command"):
			self._run_through(inv, sub, last_day=14)

		doc = frappe.get_doc("Invoice", inv)
		transition(doc, "Cancelled", reason="reissue", actor="test")
		with patch("central.resource_actions.submit_billing_command") as start:
			doc.save(ignore_permissions=True)

		self.assertEqual(self._standing(sub), "Suspended")
		start.assert_not_called()

	def test_a_server_stopped_for_nonpayment_cannot_be_started(self):
		from central.resource_actions import submit_command

		sub = self._subscription()
		server = self._running(sub)
		inv = self._open_invoice(sub)
		with patch("central.resource_actions.submit_billing_command"):
			self._run_through(inv, sub, last_day=14)
		frappe.db.set_value("Virtual Machine", server, "status", "Stopped")

		with self.assertRaises(Exception) as caught:
			submit_command("start", TEAM, server)
		self.assertEqual(caught.exception.envelope["code"], "PAYMENT_OVERDUE")

	def test_a_server_the_customer_stopped_cannot_be_started_while_suspended(self):
		from central.resource_actions import submit_command

		sub = self._subscription()
		server = self._running(sub)
		frappe.db.set_value("Virtual Machine", server, "status", "Stopped")
		inv = self._open_invoice(sub)
		self._run_through(inv, sub, last_day=14)

		self.assertFalse(frappe.db.get_value("Subscription", sub, "stopped_for_nonpayment"))
		with self.assertRaises(Exception) as caught:
			submit_command("start", TEAM, server)
		self.assertEqual(caught.exception.envelope["code"], "PAYMENT_OVERDUE")

	def test_a_payment_by_webhook_starts_the_servers_as_the_system(self):
		from central.billing.states import transition

		sub = self._subscription()
		server = self._running(sub)
		inv = self._open_invoice(sub)
		with patch("central.resource_actions.submit_billing_command"):
			self._run_through(inv, sub, last_day=14)
		frappe.db.set_value("Virtual Machine", server, "status", "Stopped")

		doc = frappe.get_doc("Invoice", inv)
		transition(doc, "Paid", reason="test payment", actor="test")
		frappe.set_user("Guest")
		try:
			with patch(
				"central.infrastructure.doctype.resource_action.resource_action.ResourceAction.enqueue"
			):
				doc.save(ignore_permissions=True)
		finally:
			frappe.set_user("Administrator")

		self.assertTrue(frappe.db.exists("Resource Action", {"server": server, "action": "start"}))
		self.assertFalse(frappe.db.exists("Error Log", {"reference_name": sub}))

	def test_a_team_with_only_services_is_suspended(self):
		sub = self._subscription()
		frappe.db.set_value("Subscription", sub, {"server_id": None, "service_subject": "svc-dunning"})
		inv = self._open_invoice(sub)
		with declining_gateway():
			for d in (1, 3, 7):
				dunning.process_invoice_dunning(inv, now=day(d))
			out = dunning.process_invoice_dunning(inv, now=day(14))

		self.assertEqual(self._standing(sub), "Suspended")
		self.assertIn("suspend", out["actions"])

	def test_the_ladder_follows_billing_settings(self):
		"""A shortened ladder escalates on its own days, not the shipped ones."""
		sub = self._subscription()
		self._running(sub)
		inv = self._open_invoice(sub)
		results = []
		with billing_settings(dunning_retry_days="1, 2", suspend_after_days=4, terminate_after_days=6):
			with declining_gateway(), patch("central.resource_actions.submit_billing_command"):
				for d in (1, 2, 4, 6):
					results.append(dunning.process_invoice_dunning(inv, now=day(d)))

		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Overdue")
		self.assertIn("suspend", results[2]["actions"])
		self.assertIn("termination_due", results[3]["actions"])

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


class TestTheLadderIsAList(IntegrationTestCase):
	"""The schedule is date arithmetic over the policy, so it can be drawn without
	being run — and the executor walks the same list."""

	START = "2026-06-01"

	def _policy(self, retries=(1, 3, 7), suspend=14, terminate=44):
		return frappe._dict(
			retry_days=list(retries),
			overdue_after=list(retries)[-1] if retries else 0,
			suspend_after=suspend,
			terminate_after=terminate,
		)

	def _on(self, schedule, stage, attempt=None):
		return next(s for s in schedule if s.stage == stage and (attempt is None or s.attempt == attempt))

	def test_every_stage_lands_the_configured_number_of_days_out(self):
		sched = dunning.dunning_schedule(self.START, self._policy())
		self.assertEqual(str(self._on(sched, "Retry", 1).date), "2026-06-02")
		self.assertEqual(str(self._on(sched, "Retry", 3).date), "2026-06-08")
		self.assertEqual(str(self._on(sched, "Overdue").date), "2026-06-08")
		self.assertEqual(str(self._on(sched, "Suspend").date), "2026-06-15")
		self.assertEqual(str(self._on(sched, "Terminate").date), "2026-07-15")

	def test_the_ladder_is_ordered_and_a_retry_precedes_the_overdue_it_shares_a_day_with(self):
		sched = dunning.dunning_schedule(self.START, self._policy())
		self.assertEqual([s.day for s in sched], sorted(s.day for s in sched))
		last_retry = [i for i, s in enumerate(sched) if s.stage == "Retry"][-1]
		overdue = next(i for i, s in enumerate(sched) if s.stage == "Overdue")
		self.assertLess(last_retry, overdue)

	def test_with_no_retries_the_invoice_is_overdue_immediately(self):
		sched = dunning.dunning_schedule(self.START, self._policy(retries=()))
		self.assertEqual(str(self._on(sched, "Overdue").date), self.START)
		self.assertFalse([s for s in sched if s.stage == "Retry"])

	def test_an_explicit_policy_is_used_instead_of_the_settings(self):
		sched = dunning.dunning_schedule(self.START, self._policy(retries=(2,), suspend=5, terminate=9))
		self.assertEqual(str(self._on(sched, "Suspend").date), "2026-06-06")
		self.assertEqual(str(self._on(sched, "Terminate").date), "2026-06-10")

	def test_nothing_is_reached_before_the_clock_starts(self):
		sched = dunning.dunning_schedule(self.START, self._policy())
		self.assertEqual(dunning.stages_reached(sched, "2026-05-31"), set())
		self.assertEqual(dunning.stages_reached(sched, self.START), set())

	def test_stages_accumulate_as_the_dates_pass(self):
		sched = dunning.dunning_schedule(self.START, self._policy())
		self.assertEqual(dunning.stages_reached(sched, "2026-06-02"), {"Retry"})
		self.assertEqual(dunning.stages_reached(sched, "2026-06-08"), {"Retry", "Overdue"})
		self.assertEqual(dunning.stages_reached(sched, "2026-06-15"), {"Retry", "Overdue", "Suspend"})
		self.assertEqual(
			dunning.stages_reached(sched, "2026-07-15"),
			{"Retry", "Overdue", "Suspend", "Terminate"},
		)

	def test_the_policy_reads_the_settings(self):
		with billing_settings(dunning_retry_days="2, 5", suspend_after_days=9, terminate_after_days=20):
			policy = dunning.dunning_policy()
		self.assertEqual(policy.retry_days, [2, 5])
		self.assertEqual(policy.overdue_after, 5)
		self.assertEqual(policy.suspend_after, 9)
		self.assertEqual(policy.terminate_after, 20)

	def test_drawing_the_ladder_touches_no_documents(self):
		with patch.object(frappe.db, "get_value") as read:
			dunning.dunning_schedule(self.START, self._policy())
			self.assertFalse(read.called)


class TestRetryableLater(IntegrationTestCase):
	"""Which failed charges a later retry day may charge again."""

	def test_a_shortfall_can_be_charged_again(self):
		self.assertTrue(decline.is_retryable_later("card_declined", "insufficient_funds"))

	def test_a_hard_decline_is_never_charged_again(self):
		self.assertFalse(decline.is_retryable_later("expired_card", None))
		self.assertFalse(decline.is_retryable_later("card_declined", "expired_card"))
		self.assertFalse(decline.is_retryable_later("card_declined", "stolen_card"))

	def test_an_ambiguous_failure_is_not_charged_again(self):
		self.assertFalse(decline.is_retryable_later("processing_error", None))


class TestOneBadInvoiceDoesNotStopTheRun(DunningTestBase):
	def test_the_next_invoice_is_dunned_after_one_fails(self):
		sub = self._subscription(with_card=False)
		broken = self._open_invoice(sub)
		april = {
			"period_start": "2026-04-01",
			"period_end": "2026-04-30",
			"period_key": f"{TEAM}|2026-04-01|2026-04-30",
		}
		frappe.db.set_value("Invoice", broken, april)  # one live invoice per period
		healthy = self._open_invoice(sub, total=2000)
		real = dunning.process_invoice_dunning

		def process(name, now=None):
			if name == broken:
				raise RuntimeError("bad row")
			return real(name, now=now)

		with patch.object(dunning, "process_invoice_dunning", side_effect=process):
			results = dunning.run_dunning(now=day(7))

		self.assertIn({"name": broken, "failed": True}, results)
		self.assertEqual(frappe.db.get_value("Invoice", healthy, "status"), "Overdue")
