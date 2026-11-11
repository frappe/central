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
from central.billing.platform.records import save_billing_record
from central.billing.revenue import dunning
from central.billing.tests.test_stripe_adapter import make_stripe_gateway
from central.billing.tests.utils import (
	BillingTestCase,
	complete_billing_profile,
	ensure_atlas_instance,
	ensure_team,
	make_plan,
	set_team_tier,
)

TEAM = "team-dunning"
CLUSTER = "ap-south-1"
PLAN = "bundle-dunning-test"
GATEWAY = "Stripe"
# An invoice opened on the 1st with payment day 1. With the ladder below it is retried on
# the 3rd, 5th and 7th, is Overdue on the 7th, suspended on the 15th and due for
# termination on the 25th.
PAY = "2026-06-01"
DUE = "2026-06-08"
SUSPENDS_ON = "2026-06-15"
LADDER = {
	"dunning_retry_interval_days": 2,
	"invoice_due_days": 7,
	"suspension_day": 15,
	"terminate_after_days": 10,
}


@contextmanager
def gateway_answering(result: PaymentResult):
	adapter = MagicMock()
	adapter.prepare_charge.return_value = None  # Stripe-like: no order to store
	adapter.charge.return_value = result
	with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
		yield adapter


def declining_gateway(failure_code="card_declined", decline_code=None):
	return gateway_answering(
		PaymentResult(
			success=False,
			status="Failed",
			failure_code=failure_code,
			decline_code=decline_code,
			failure_reason="Card declined",
		)
	)


def capturing_gateway():
	"""The gateway takes the charge and confirms it later by webhook, so the attempt stays in flight."""
	return gateway_answering(PaymentResult(success=True, status="captured", gateway_transaction_id="pi_x"))


def day(n):
	return frappe.utils.add_days(PAY, n)


class DunningTestBase(BillingTestCase):
	def setUp(self):
		ensure_team(TEAM)
		ensure_atlas_instance(CLUSTER)
		make_plan(PLAN)
		make_stripe_gateway()
		set_team_tier(TEAM, level="t1", max_spend=50000)
		self.enterContext(settings.overridden(**LADDER))

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
					"status": "Outstanding",
					"period_start": "2026-05-01",
					"period_end": "2026-05-31",
					"currency": "INR",
					"subtotal": total,
					"total": total,
					"expected_collection": total,
					"due_date": DUE,
					"payment_date": PAY,
					"dunning_starts_on": PAY,
					"suspends_on": SUSPENDS_ON,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _attempts(self, inv):
		return frappe.db.count("Payment Attempt", {"invoice": inv})

	def _dun(self, inv, n):
		with self.freeze_time(f"{day(n)} 03:00:00"):
			return dunning.process_invoice_dunning(inv, now=day(n))

	def _overdue_notices(self, inv):
		return frappe.db.count(
			"Billing Notification Log", {"team": TEAM, "event_type": "Invoice Overdue", "reference_name": inv}
		)

	def _fail(self, attempt, at):
		frappe.db.set_value(
			"Payment Attempt",
			attempt,
			{
				"status": "Failed",
				"failure_code": "card_declined",
				"decline_code": "insufficient_funds",
				"completed_at": at,
			},
		)

	def _last_attempt(self, inv):
		return frappe.get_all(
			"Payment Attempt", {"invoice": inv}, order_by="creation desc", limit=1, pluck="name"
		)[0]

	def _standing(self, sub):
		return frappe.db.get_value("Subscription", sub, "account_standing")


class TestRetrySchedule(DunningTestBase):
	"""Each retry day is a new collection round: a card whose decline can clear is
	charged again, once per round. A hard decline is never charged again."""

	def test_a_declined_card_is_retried_on_each_retry_day(self):
		inv = self._open_invoice(self._subscription())
		with declining_gateway(decline_code="insufficient_funds"):
			for n, attempts in ((2, 1), (3, 1), (4, 2), (6, 3)):
				self._dun(inv, n)
				self.assertEqual(self._attempts(inv), attempts, f"day {n}")

	def test_a_hard_decline_is_not_retried(self):
		inv = self._open_invoice(self._subscription())
		with declining_gateway(decline_code="stolen_card"):
			self._dun(inv, 2)
			self._dun(inv, 4)
			self._dun(inv, 6)
		self.assertEqual(self._attempts(inv), 1)

	def test_an_expired_card_is_not_retried(self):
		inv = self._open_invoice(self._subscription())
		with declining_gateway(failure_code="expired_card"):
			self._dun(inv, 2)
			self._dun(inv, 4)
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
			self._dun(inv, 2)
			self.assertEqual(self._attempts(inv), 2)
			self._dun(inv, 4)
			self.assertEqual(self._attempts(inv), 4)

	def test_a_round_charges_a_card_once_whatever_the_clock_says(self):
		inv = self._open_invoice(self._subscription())
		with declining_gateway(decline_code="insufficient_funds"):
			dunning.process_invoice_dunning(inv, now="2030-01-01")
		self.assertEqual(self._attempts(inv), 1)

	def test_same_day_rerun_does_not_double_retry(self):
		inv = self._open_invoice(self._subscription())
		with declining_gateway():
			self._dun(inv, 2)
			self._dun(inv, 2)
		self.assertEqual(self._attempts(inv), 1)


class TestStagedEscalation(DunningTestBase):
	def _run_through(self, inv, sub, last_day):
		with declining_gateway():
			for d in (2, 4, 6, 14, 24):
				if d <= last_day:
					dunning.process_invoice_dunning(inv, now=day(d))

	def _running(self, sub):
		server = frappe.db.get_value("Subscription", sub, "server_id")
		frappe.db.set_value("Virtual Machine", server, {"status": "Running", "atlas_vm_id": "vm-dunning"})
		return server

	def test_the_last_retry_day_marks_overdue_and_past_due_still_running(self):
		sub = self._subscription()
		self._running(sub)
		inv = self._open_invoice(sub)
		with patch("central.resource_actions.submit_billing_command") as stop:
			self._run_through(inv, sub, last_day=6)

		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Overdue")
		self.assertEqual(self._standing(sub), "Past Due")  # grace
		stop.assert_not_called()  # late is not yet cut off

	def test_overdue_waits_for_the_last_retry_still_in_flight(self):
		inv = self._open_invoice(self._subscription())
		with declining_gateway(decline_code="insufficient_funds"):
			self._dun(inv, 2)
			self._dun(inv, 4)
		with capturing_gateway():
			result = self._dun(inv, 6)

		self.assertEqual(result["actions"], ["retry"])
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Outstanding")
		self.assertEqual(self._overdue_notices(inv), 0)

		self._fail(self._last_attempt(inv), f"{day(6)} 09:00:00")
		result = self._dun(inv, 7)

		self.assertEqual(result["actions"], ["overdue"])
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Overdue")
		self.assertEqual(self._overdue_notices(inv), 1)

	def test_the_last_retry_day_moves_every_subscription_of_the_team(self):
		"""The invoice bills the whole team, so Overdue marks every server, as suspension suspends every one."""
		sub = self._subscription()
		second = self._subscription(with_card=False)
		inv = self._open_invoice(sub)
		with patch("central.resource_actions.submit_billing_command"):
			self._run_through(inv, sub, last_day=6)

		self.assertEqual((self._standing(sub), self._standing(second)), ("Past Due", "Past Due"))

	def test_the_suspension_date_stops_running_servers(self):
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

	def test_termination_is_due_after_suspension_and_nothing_is_deleted(self):
		from central.billing.platform import alerts

		sub = self._subscription()
		inv = self._open_invoice(sub)
		with (
			patch("central.resource_actions.submit_billing_command"),
			patch("central.api.servers.terminate_server") as end,
		):
			self._run_through(inv, sub, last_day=23)
			before = dunning.process_invoice_dunning(inv, now=day(23))
			out = dunning.process_invoice_dunning(inv, now=day(24))

		self.assertNotIn("termination_due", before["actions"])
		self.assertIn("termination_due", out["actions"])
		end.assert_not_called()
		with patch("frappe.utils.nowdate", return_value=day(24)):
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
			save_billing_record(doc)

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
			save_billing_record(doc)

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
				save_billing_record(doc)
		finally:
			frappe.set_user("Administrator")

		self.assertTrue(frappe.db.exists("Resource Action", {"server": server, "action": "start"}))
		self.assertFalse(frappe.db.exists("Error Log", {"reference_name": sub}))

	def test_a_team_with_only_services_is_suspended(self):
		sub = self._subscription()
		frappe.db.set_value("Subscription", sub, {"server_id": None, "service_subject": "svc-dunning"})
		inv = self._open_invoice(sub)
		with declining_gateway():
			for d in (2, 4, 6):
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
		with settings.overridden(dunning_retry_interval_days=3, terminate_after_days=2):
			with declining_gateway(), patch("central.resource_actions.submit_billing_command"):
				for d in (3, 6, 14, 16):
					results.append(dunning.process_invoice_dunning(inv, now=day(d)))

		self.assertIn("retry", results[0]["actions"])
		self.assertIn("overdue", results[1]["actions"])
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
		for d in (6, 14):
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

		# The last retry day with no deferral: the invoice would go Overdue and the team
		# past_due. The rate limit lands first, so the same day must do nothing instead.
		with self.freeze_time(f"{day(6)} 03:00:00"):
			dunning.defer_dunning(inv, "429 from the gateway")
			result = dunning.process_invoice_dunning(inv, now=day(6))

		self.assertEqual(result["action"], "none")
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Outstanding")
		self.assertNotEqual(self._standing(sub), "Past Due")

	def test_deferring_moves_the_whole_ladder_by_the_same_days(self):
		sub = self._subscription()
		inv = self._open_invoice(sub)
		with self.freeze_time(f"{day(3)} 03:00:00"):
			dunning.defer_dunning(inv, "the run backed up")

		row = frappe.db.get_value("Invoice", inv, ["name", *dunning.LADDER_FIELDS], as_dict=True)
		dates = dunning.get_ladder_dates(row)
		schedule = dunning.dunning_schedule(dates)
		retries = [str(s.date) for s in schedule if s.stage == "Retry"]
		self.assertEqual(str(row.dunning_starts_on), "2026-06-04")
		self.assertEqual(retries, ["2026-06-06", "2026-06-08", "2026-06-10"])
		self.assertEqual(str(row.suspends_on), "2026-06-18")
		self.assertTrue(dates.is_deferred)

	def test_the_deferred_ladder_still_runs_from_the_fair_date(self):
		sub = self._subscription()
		inv = self._open_invoice(sub)
		with self.freeze_time(f"{day(3)} 03:00:00"):
			dunning.defer_dunning(inv, "the run backed up")

		# Deferral is grace, not amnesty: on the moved last retry day the ladder
		# escalates exactly as it always would.
		with declining_gateway():
			dunning.process_invoice_dunning(inv, now=day(9))
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Overdue")

	def test_deferral_only_ever_moves_forward(self):
		# Day 2 of a three-day backlog must not hand back the grace day 1 granted,
		# and a stale failure arriving late must not rewind an already-fair clock.
		sub = self._subscription()
		inv = self._open_invoice(sub)
		with self.freeze_time(f"{day(3)} 03:00:00"):
			self.assertTrue(dunning.defer_dunning(inv, "first failure"))
			self.assertFalse(dunning.defer_dunning(inv, "same day, second failure"))
		with self.freeze_time(f"{day(1)} 03:00:00"):
			self.assertFalse(dunning.defer_dunning(inv, "a stale failure"))

		self.assertEqual(str(frappe.db.get_value("Invoice", inv, "dunning_starts_on")), "2026-06-04")
		self.assertEqual(str(frappe.db.get_value("Invoice", inv, "suspends_on")), "2026-06-18")

	def test_an_invoice_that_collected_normally_keeps_the_payment_date_clock(self):
		# The fairness rule must not slow down dunning for everyone else.
		sub = self._subscription()
		inv = self._open_invoice(sub)

		with declining_gateway():
			result = dunning.process_invoice_dunning(inv, now=day(6))
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Overdue")
		self.assertEqual(result["days_overdue"], 6)

	def test_deferring_never_touches_the_due_date(self):
		# What the customer owed and when is an accounting fact; AR aging keeps
		# reading it. Only the escalation clock moves.
		sub = self._subscription()
		inv = self._open_invoice(sub)
		with self.freeze_time(f"{day(3)} 03:00:00"):
			dunning.defer_dunning(inv, "the run backed up")
		self.assertEqual(str(frappe.db.get_value("Invoice", inv, "due_date")), DUE)


class TestTheLadderIsAList(DunningTestBase):
	"""The schedule is date arithmetic over the ladder dates, so it can be drawn without
	being run — and the executor walks the same list."""

	DATES = frappe._dict(
		anchor=PAY,
		retry_until=DUE,
		suspends_on=SUSPENDS_ON,
		first_failed_at=None,
		in_flight_since=None,
		is_awaiting_charge=False,
	)

	def _policy(self, interval=2, terminate=10):
		return frappe._dict(retry_interval=interval, terminate_after=terminate)

	def _on(self, schedule, stage, attempt=None):
		return next(s for s in schedule if s.stage == stage and (attempt is None or s.attempt == attempt))

	def _ladder_for_payment_day(self, payment_day, opened_on="2026-06-01"):
		frappe.db.set_value("Billing Profile", TEAM, "payment_day", payment_day)
		dates = dunning.get_opening_ladder_dates(TEAM, opened_on)
		schedule = dunning.dunning_schedule(dates)
		return {
			"retries": [s.date.day for s in schedule if s.stage == "Retry"],
			"overdue": self._on(schedule, "Overdue").date.day,
			"suspend": str(self._on(schedule, "Suspend").date),
			"terminate": str(self._on(schedule, "Terminate").date),
		}

	def test_each_payment_day_gets_its_retries_before_the_suspension_day(self):
		complete_billing_profile(TEAM)
		expected = {1: [3, 5, 7], 3: [5, 7], 5: [7], 6: [8], 7: [8], 8: [9], 10: [11]}
		for payment_day, retries in expected.items():
			with self.subTest(payment_day=payment_day):
				ladder = self._ladder_for_payment_day(payment_day)
				self.assertEqual(ladder["retries"], retries)
				self.assertEqual(ladder["overdue"], retries[-1])
				self.assertEqual(ladder["suspend"], "2026-06-15")
				self.assertEqual(ladder["terminate"], "2026-06-25")

	def test_an_invoice_opened_after_the_suspension_day_is_suspended_a_week_after_its_due_date(self):
		complete_billing_profile(TEAM)
		ladder = self._ladder_for_payment_day(1, opened_on="2026-06-20")

		self.assertEqual(ladder["retries"], [22, 24, 26])
		self.assertEqual(ladder["suspend"], "2026-07-04")
		self.assertEqual(ladder["terminate"], "2026-07-14")

	def test_the_ladder_is_ordered_and_a_retry_precedes_the_overdue_it_shares_a_day_with(self):
		sched = dunning.dunning_schedule(self.DATES, self._policy())
		self.assertEqual([s.date for s in sched], sorted(s.date for s in sched))
		last_retry = [i for i, s in enumerate(sched) if s.stage == "Retry"][-1]
		overdue = next(i for i, s in enumerate(sched) if s.stage == "Overdue")
		self.assertLess(last_retry, overdue)

	def test_an_explicit_policy_is_used_instead_of_the_settings(self):
		sched = dunning.dunning_schedule(self.DATES, self._policy(interval=3, terminate=4))
		self.assertEqual([str(s.date) for s in sched if s.stage == "Retry"], ["2026-06-04", "2026-06-07"])
		self.assertEqual(str(self._on(sched, "Terminate").date), "2026-06-19")

	def test_nothing_is_reached_before_the_first_retry(self):
		sched = dunning.dunning_schedule(self.DATES, self._policy())
		self.assertEqual(dunning.stages_reached(sched, "2026-05-31"), set())
		self.assertEqual(dunning.stages_reached(sched, "2026-06-02"), set())

	def test_stages_accumulate_as_the_dates_pass(self):
		sched = dunning.dunning_schedule(self.DATES, self._policy())
		self.assertEqual(dunning.stages_reached(sched, "2026-06-03"), {"Retry"})
		self.assertEqual(dunning.stages_reached(sched, "2026-06-07"), {"Retry", "Overdue"})
		self.assertEqual(dunning.stages_reached(sched, "2026-06-15"), {"Retry", "Overdue", "Suspend"})
		self.assertEqual(
			dunning.stages_reached(sched, "2026-06-25"),
			{"Retry", "Overdue", "Suspend", "Terminate"},
		)

	def test_the_policy_reads_the_settings(self):
		with settings.overridden(dunning_retry_interval_days=3, terminate_after_days=20):
			policy = dunning.dunning_policy()
		self.assertEqual(policy.retry_interval, 3)
		self.assertEqual(policy.terminate_after, 20)

	def test_the_last_payment_day_with_interval_retries(self):
		with settings.overridden(dunning_retry_interval_days=2, invoice_due_days=7):
			self.assertEqual(dunning.get_last_payment_day_with_retries(), 6)
		with settings.overridden(dunning_retry_interval_days=1, invoice_due_days=7):
			self.assertEqual(dunning.get_last_payment_day_with_retries(), 7)

	def test_drawing_the_ladder_touches_no_documents(self):
		with patch.object(frappe.db, "get_value") as read:
			dunning.dunning_schedule(self.DATES, self._policy())
			self.assertFalse(read.called)


class TestTheSingleRetry(DunningTestBase):
	"""Payment day 8: the first interval retry falls after the due date, so the ladder has one
	retry, 24 hours after the first charge failed. The hourly sweep runs it."""

	PAY = "2026-06-08"

	def _open_on_payment_day(self):
		inv = self._open_invoice(self._subscription())
		frappe.db.set_value(
			"Invoice", inv, {"payment_date": self.PAY, "due_date": self.PAY, "dunning_starts_on": self.PAY}
		)
		return inv

	def _run_hourly_sweep(self, at):
		from central.billing.payments import collection

		with self.freeze_time(at):
			collection.collect_on_payment_date(now=at)

	def test_a_charge_that_failed_late_is_retried_a_full_day_later(self):
		inv = self._open_on_payment_day()
		with declining_gateway(decline_code="insufficient_funds"):
			self._run_hourly_sweep("2026-06-08 23:00:00")
			self.assertEqual(self._attempts(inv), 1)

			with self.freeze_time("2026-06-09 00:30:00"):
				dunning.process_invoice_dunning(inv, now="2026-06-09 00:30:00")
			self.assertEqual(self._attempts(inv), 1)
			self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Outstanding")

			self._run_hourly_sweep("2026-06-09 22:00:00")
			self.assertEqual(self._attempts(inv), 1)

			self._run_hourly_sweep("2026-06-09 23:00:00")
			self.assertEqual(self._attempts(inv), 2)
			self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Overdue")

			self._run_hourly_sweep("2026-06-10 00:00:00")
			self.assertEqual(self._attempts(inv), 2)

	def test_the_ladder_dates_the_single_retry_from_the_failed_charge(self):
		dates = frappe._dict(
			anchor=self.PAY,
			retry_until=self.PAY,
			suspends_on=SUSPENDS_ON,
			first_failed_at=None,
			in_flight_since=None,
			is_awaiting_charge=False,
		)
		failed = frappe._dict(dates, first_failed_at="2026-06-09 05:00:00")
		schedule = dunning.dunning_schedule(failed)
		retry = next(s for s in schedule if s.stage == "Retry")
		self.assertEqual(str(retry.at), "2026-06-10 05:00:00")
		self.assertEqual(str(next(s for s in schedule if s.stage == "Overdue").at), "2026-06-10 05:00:00")

		without_failure = next(s for s in dunning.dunning_schedule(dates) if s.stage == "Retry")
		self.assertEqual(str(without_failure.date), "2026-06-09")

		awaiting = frappe._dict(dates, is_awaiting_charge=True)
		self.assertEqual(
			[(s.stage, str(s.date)) for s in dunning.dunning_schedule(awaiting)][:2],
			[("Overdue", "2026-06-14"), ("Suspend", "2026-06-15")],
		)

	def _attempt(self, inv, status, at):
		attempt = frappe.get_doc(
			{
				"doctype": "Payment Attempt",
				"invoice": inv,
				"team": TEAM,
				"gateway": GATEWAY,
				"payment_method": frappe.db.get_value("Payment Method", {"team": TEAM}),
				"amount": 1000,
				"currency": "INR",
				"status": status,
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Payment Attempt", attempt.name, "creation", at, update_modified=False)
		return attempt.name

	def _run_hourly_single_retry(self, inv, at):
		row = frappe.db.get_value("Invoice", inv, ["name", *dunning.LADDER_FIELDS], as_dict=True)
		with self.freeze_time(at):
			return dunning._run_single_retry(
				row, dunning.get_ladder_dates(row), dunning.dunning_policy(), frappe.utils.get_datetime(at)
			)

	def test_the_retry_and_overdue_wait_for_a_charge_in_flight(self):
		inv = self._open_on_payment_day()
		# The first-charge sweep is late: no attempt yet on a team dunning can charge.
		self.assertEqual(dunning.process_invoice_dunning(inv, now="2026-06-09 12:00:00")["action"], "none")

		attempt = self._attempt(inv, "Initiated", "2026-06-09 12:30:00")
		result = dunning.process_invoice_dunning(inv, now="2026-06-10 12:00:00")

		self.assertEqual(result["action"], "none")
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Outstanding")
		self.assertEqual(self._overdue_notices(inv), 0)
		self.assertEqual(self._attempts(inv), 1)

		self._fail(attempt, "2026-06-10 15:00:00")
		with declining_gateway(decline_code="insufficient_funds"):
			self.assertEqual(self._run_hourly_single_retry(inv, "2026-06-11 14:00:00")["skipped"], "not_due")
			result = self._run_hourly_single_retry(inv, "2026-06-11 15:00:00")

		self.assertEqual(result["actions"], ["retry", "overdue"])
		self.assertEqual(self._attempts(inv), 2)
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Overdue")
		self.assertEqual(self._overdue_notices(inv), 1)

	def test_a_team_dunning_cannot_charge_goes_overdue_the_day_after_the_payment_date(self):
		inv = self._open_invoice(self._subscription(with_card=False))
		frappe.db.set_value(
			"Invoice", inv, {"payment_date": self.PAY, "due_date": self.PAY, "dunning_starts_on": self.PAY}
		)

		dunning.process_invoice_dunning(inv, now="2026-06-08 23:00:00")
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Outstanding")

		dunning.process_invoice_dunning(inv, now="2026-06-09 00:00:00")
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Overdue")
		self.assertEqual(self._overdue_notices(inv), 1)

	def test_only_a_team_dunning_can_charge_waits_for_its_first_charge(self):
		inv = self._open_on_payment_day()
		row = frappe.db.get_value("Invoice", inv, ["name", *dunning.LADDER_FIELDS], as_dict=True)
		self.assertTrue(dunning.get_ladder_dates(row).is_awaiting_charge)

		frappe.db.set_value("Billing Profile", TEAM, "collection_mode", "Manual Checkout")
		self.assertFalse(dunning.get_ladder_dates(row).is_awaiting_charge)

	def test_a_single_retry_in_flight_holds_overdue_until_it_fails(self):
		inv = self._open_on_payment_day()
		self._fail(self._attempt(inv, "Initiated", "2026-06-08 09:00:00"), "2026-06-08 10:00:00")
		with capturing_gateway():
			result = self._run_hourly_single_retry(inv, "2026-06-09 10:00:00")

		self.assertEqual(result["actions"], ["retry"])
		self.assertEqual(self._attempts(inv), 2)
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Outstanding")
		self.assertEqual(self._overdue_notices(inv), 0)

		self._fail(self._last_attempt(inv), "2026-06-09 18:00:00")
		with self.freeze_time("2026-06-10 03:00:00"):
			result = dunning.process_invoice_dunning(inv, now="2026-06-10 03:00:00")

		self.assertEqual(result["actions"], ["overdue"])
		self.assertEqual(self._attempts(inv), 2)
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Overdue")
		self.assertEqual(self._overdue_notices(inv), 1)

	def test_a_retry_that_would_land_after_the_suspension_is_not_run(self):
		inv = self._open_on_payment_day()
		self._fail(self._attempt(inv, "Initiated", "2026-06-14 09:00:00"), "2026-06-14 10:00:00")

		schedule = dunning.dunning_schedule(dunning.get_ladder_dates(frappe.get_doc("Invoice", inv)))
		self.assertEqual(
			[(s.stage, str(s.at)) for s in schedule[:2]],
			[("Overdue", "2026-06-14 00:00:00"), ("Suspend", "2026-06-15 00:00:00")],
		)

		with declining_gateway(), patch("central.resource_actions.submit_billing_command"):
			result = dunning.process_invoice_dunning(inv, now="2026-06-15 11:00:00")

		self.assertEqual(result["actions"], ["overdue", "suspend"])
		self.assertEqual(self._attempts(inv), 1)

	def test_a_charge_in_flight_goes_overdue_the_day_before_the_suspension(self):
		inv = self._open_on_payment_day()
		self._attempt(inv, "Initiated", "2026-06-08 00:30:00")
		self.assertEqual(dunning.process_invoice_dunning(inv, now="2026-06-13 23:00:00")["action"], "none")

		with self.freeze_time("2026-06-14 03:00:00"):
			result = dunning.process_invoice_dunning(inv, now="2026-06-14 03:00:00")

		self.assertEqual(result["actions"], ["overdue"])
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Overdue")
		message = frappe.db.get_value(
			"Billing Notification Log", {"event_type": "Invoice Overdue", "reference_name": inv}, "message"
		)
		self.assertIn("still processing", message)
		self.assertIn("15 June 2026", message)

		with patch("central.resource_actions.submit_billing_command"):
			result = dunning.process_invoice_dunning(inv, now=SUSPENDS_ON)

		self.assertEqual(result["actions"], ["suspend"])
		self.assertEqual(frappe.db.get_value("Subscription", {"team": TEAM}, "account_standing"), "Suspended")
		self.assertEqual(self._overdue_notices(inv), 1)

	def test_a_charge_that_fails_after_the_suspension_leaves_the_invoice_overdue(self):
		inv = self._open_on_payment_day()
		attempt = self._attempt(inv, "Initiated", "2026-06-08 00:30:00")
		self._fail(attempt, "2026-06-16 10:00:00")

		with patch("central.resource_actions.submit_billing_command"):
			result = dunning.process_invoice_dunning(inv, now="2026-06-17 03:00:00")

		self.assertEqual(result["actions"], ["overdue", "suspend"])
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Overdue")
		self.assertEqual(self._attempts(inv), 1)


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

		self.assertNotIn(broken, [result["invoice"] for result in results])
		self.assertIn(healthy, [result["invoice"] for result in results])
		self.assertEqual(frappe.db.get_value("Invoice", healthy, "status"), "Overdue")
