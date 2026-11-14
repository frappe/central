# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Top-up reminders before the payment date for INR bills above the card or UPI limit (#191)."""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import frappe

from central.billing.payments import top_up_reminders
from central.billing.revenue import credits, invoicing
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import complete_billing_profile, ensure_team

TEAM = "team-top-up-reminders"
EVENT = top_up_reminders.EVENT
# Payment day 1: the bill is paid on 1 December, so 26 and 29 November are the reminder days.
REMINDER_DAYS = ("2026-11-26", "2026-11-29")


def _reminders(team=TEAM) -> list[frappe._dict]:
	return frappe.get_all(
		"Billing Notification Log",
		filters={"team": team, "event_type": EVENT},
		fields=["message", "status", "reference_name"],
	)


def _add_upi(team=TEAM) -> None:
	"""A UPI Autopay method with no mandate cap: the ₹15,000 ceiling is its limit."""
	from central.billing.tests.test_razorpay_adapter import make_razorpay_gateway

	frappe.get_doc(
		{
			"doctype": "Payment Method",
			"team": team,
			"gateway": make_razorpay_gateway().name,
			"method_type": "UPI Autopay",
			"status": "Active",
			"gateway_method_id": f"tok_{team}",
			"mandate_currency": "INR",
		}
	).insert(ignore_permissions=True)


def _forecast_of(total) -> dict:
	"""A forecast of `total` that the wallet does not pay."""
	return {"projected_total": total, "shortfall": total, "tax_note": None, "limit_tax_note": None}


def _set_mode(mode, team=TEAM) -> None:
	frappe.db.set_value("Billing Profile", team, "collection_mode", mode)


class TopUpTestCase(IntegrationTestCase):
	forecast = 40000

	def setUp(self):
		ensure_team(TEAM)
		complete_billing_profile(TEAM)
		frappe.db.set_value("Billing Profile", TEAM, {"payment_day": 1, "collection_mode": "Prepaid"})
		self._purge()
		_add_upi()
		forecast = patch.object(top_up_reminders, "get_forecast_total", side_effect=lambda *a: self.forecast)
		forecast.start()
		self.addCleanup(forecast.stop)
		# No test may reach a gateway.
		adapter = patch("central.billing.gateways.registry.get_adapter", return_value=MagicMock())
		adapter.start()
		self.addCleanup(adapter.stop)

	def tearDown(self):
		self._purge()

	def _purge(self):
		for doctype in ("Billing Notification Log", "Team Notification", "User Notification Preference"):
			frappe.db.delete(doctype, {"team": TEAM})
		frappe.db.delete("Payment Method", {"team": TEAM})

	def _run(self, day: str) -> list[dict]:
		with self.freeze_time(f"{day} 09:00:00"):
			teams = top_up_reminders.get_due_teams(frappe.utils.getdate())
			return [top_up_reminders.remind_team(team, day) for team in teams if team == TEAM]


class TestWhenTheReminderGoesOut(TopUpTestCase):
	def test_the_team_is_reminded_5_and_2_days_before_the_payment_date(self):
		for day in REMINDER_DAYS:
			self.assertEqual(self._run(day), [{"team": TEAM, "reminded": True}])

		messages = [row.message for row in _reminders()]
		self.assertEqual(len(messages), 2)
		self.assertIn("Add ₹ 40,000.00 of credit to your wallet by 1 December 2026.", messages[0])
		self.assertIn("Your card or UPI pays only amounts up to ₹ 15,000.00.", messages[0])

	def test_no_other_day_and_not_the_payment_day(self):
		for day in ("2026-11-25", "2026-11-27", "2026-11-30", "2026-12-01"):
			self._run(day)

		self.assertEqual(_reminders(), [])

	def test_a_second_run_on_the_same_day_sends_nothing(self):
		self._run(REMINDER_DAYS[0])

		self.assertEqual(self._run(REMINDER_DAYS[0]), [{"team": TEAM, "skipped": "already_reminded"}])
		self.assertEqual(len(_reminders()), 1)

	def test_the_daily_job_queues_the_due_teams(self):
		with self.freeze_time(f"{REMINDER_DAYS[0]} 09:00:00"), patch("frappe.enqueue") as enqueue:
			top_up_reminders.run_top_up_reminders()

		self.assertIn(TEAM, [team for call in enqueue.call_args_list for team in call.kwargs["teams"]])

	def test_an_issued_bill_is_read_from_its_invoice(self):
		frappe.db.set_value("Billing Profile", TEAM, "payment_day", 8)
		invoice = _issued_invoice(TEAM, 30000, payment_date="2026-12-08")

		self._run("2026-12-03")

		reminders = _reminders()
		self.assertEqual(len(reminders), 1)
		self.assertEqual(reminders[0].reference_name, invoice)
		self.assertIn("Add ₹ 30,000.00 of credit to your wallet by 8 December 2026.", reminders[0].message)


class TestWhoIsReminded(TopUpTestCase):
	def test_a_usd_team_is_not_reminded(self):
		frappe.db.set_value("Billing Profile", TEAM, "currency", "USD")
		self._run(REMINDER_DAYS[0])
		self.assertEqual(_reminders(), [])

	def test_manual_checkout_and_action_required_are_not_reminded(self):
		for mode in ("Manual Checkout", "Action Required"):
			_set_mode(mode)
			self._run(REMINDER_DAYS[0])
		self.assertEqual(_reminders(), [])

	def test_auto_charge_is_reminded(self):
		_set_mode("Auto Charge")
		self._run(REMINDER_DAYS[0])
		self.assertEqual(len(_reminders()), 1)

	def test_a_bill_equal_to_the_limit_is_not_reminded(self):
		self.forecast = 15000
		self._run(REMINDER_DAYS[0])
		self.assertEqual(_reminders(), [])

	def test_a_top_up_that_brings_the_bill_to_the_limit_stops_the_reminders(self):
		self._run(REMINDER_DAYS[0])
		credits.purchase(TEAM, 25000, "INR")

		self.assertEqual(self._run(REMINDER_DAYS[1]), [{"team": TEAM, "skipped": "not_due"}])
		self.assertEqual(len(_reminders()), 1)

	def test_the_amount_is_the_whole_shortfall_rounded_up_to_100(self):
		self.forecast = 40050.4
		credits.purchase(TEAM, 10000, "INR")

		due = top_up_reminders.get_top_up_due(TEAM, REMINDER_DAYS[0])

		self.assertEqual(due["amount"], 30100)
		self.assertEqual(due["date"], "2026-12-01")

	def test_a_team_with_no_card_or_upi_is_asked_for_the_shortfall(self):
		frappe.db.delete("Payment Method", {"team": TEAM})
		self.forecast = 3000

		self._run(REMINDER_DAYS[0])

		message = _reminders()[0].message
		self.assertIn("Add ₹ 3,000.00 of credit to your wallet by 1 December 2026.", message)
		self.assertIn("No card or UPI is saved to pay the rest.", message)


class TestPreferences(TopUpTestCase):
	def test_members_are_emailed_by_default(self):
		self._run(REMINDER_DAYS[0])
		self.assertEqual(_reminders()[0].status, "Queued")

	def test_email_follows_the_member_preference_and_the_feed_still_gets_it(self):
		frappe.get_doc(
			{
				"doctype": "User Notification Preference",
				"user": frappe.db.get_value("Team", TEAM, "owner_user"),
				"team": TEAM,
				"category": "Billing",
				"email_enabled": 0,
			}
		).insert(ignore_permissions=True)

		self._run(REMINDER_DAYS[0])

		self.assertEqual(_reminders()[0].status, "Suppressed")
		route = frappe.db.get_value(
			"Team Notification", {"team": TEAM, "event_type": "top_up_reminder"}, "action_route"
		)
		self.assertEqual(route, f"/billing?team={TEAM}&topup=40000")


class TestPaymentScheduledOverTheLimit(TopUpTestCase):
	"""An opened bill the card or UPI cannot pay gets one notice, never a promise to charge it."""

	def _open(self, total, when="2026-11-01 10:00:00"):
		invoice = _draft(TEAM, total)
		with self.freeze_time(when):
			invoicing.open_and_collect(invoice)
		return invoice

	def _scheduled(self):
		return frappe.get_all("Billing Notification Log", {"team": TEAM, "event_type": "Payment Scheduled"})

	def test_a_bill_over_the_limit_asks_for_a_top_up_instead(self):
		frappe.db.set_value("Billing Profile", TEAM, "payment_day", 5)
		invoice = self._open(30000)

		self.assertEqual(self._scheduled(), [])
		reminders = _reminders()
		self.assertEqual(len(reminders), 1)
		self.assertEqual(reminders[0].reference_name, invoice)
		self.assertIn("Add ₹ 30,000.00 of credit to your wallet by 5 November 2026.", reminders[0].message)

	def test_a_bill_within_the_limit_keeps_the_payment_scheduled_notice(self):
		frappe.db.set_value("Billing Profile", TEAM, "payment_day", 5)
		self._open(5000)

		self.assertEqual(len(self._scheduled()), 1)
		self.assertEqual(_reminders(), [])

	def test_a_bill_that_trips_action_required_gets_only_that_notice(self):
		self._open(30000, when="2026-12-01 10:00:00")

		self.assertEqual(frappe.db.get_value("Billing Profile", TEAM, "collection_mode"), "Action Required")
		self.assertEqual(self._scheduled(), [])
		self.assertEqual(_reminders(), [])
		self.assertEqual(len(frappe.get_all("Billing Notification Log", {"team": TEAM})), 1)


class TestBanner(TopUpTestCase):
	def test_the_collection_status_carries_the_top_up(self):
		from central.billing.api.dashboard import account

		with (
			self.freeze_time("2026-11-13 10:00:00"),
			patch("central.billing.api.dashboard.invoices.get_forecast", return_value=_forecast_of(40000)),
		):
			status = account.get_collection_status(TEAM)

		due = {key: status["top_up_due"][key] for key in ("amount", "date", "limit", "has_method")}
		self.assertEqual(due, {"amount": 40000, "date": "2026-12-01", "limit": 15000.0, "has_method": True})

	def test_the_banner_shows_the_amounts_as_the_email_does(self):
		from central.billing.api.dashboard import account

		with self._forecast(40000):
			labels = account.get_collection_status(TEAM)["top_up_due"]["labels"]

		self.assertEqual(
			labels,
			{
				"amount": "₹ 40,000.00",
				"amount_with_gst": None,
				"tax_label": None,
				"payment_date": "1 December 2026",
				"limit": "₹ 15,000.00",
				"limit_tax_note": None,
			},
		)

	def test_no_banner_once_the_card_can_pay_what_the_wallet_leaves(self):
		"""Before issue the wallet pays what it can and the card the rest."""
		from central.billing.api.dashboard import account

		credits.purchase(TEAM, 30000, "INR")
		with self._forecast(40000):
			self.assertIsNone(account.get_collection_status(TEAM)["top_up_due"])

	def test_no_banner_once_the_wallet_covers_the_bill(self):
		from central.billing.api.dashboard import account

		frappe.db.delete("Payment Method", {"team": TEAM})
		credits.purchase(TEAM, 40000, "INR")
		with self._forecast(40000):
			self.assertIsNone(account.get_collection_status(TEAM)["top_up_due"])

	def test_auto_charge_over_the_limit_after_the_wallet_sees_the_top_up(self):
		"""A forecast only informs: the read never moves the team to Action Required."""
		from central.billing.api.dashboard import account

		_set_mode("Auto Charge")
		with self._forecast(40000):
			status = account.get_collection_status(TEAM)

		self.assertFalse(status["action_required"])
		self.assertEqual(status["collection_mode"], "Auto Charge")
		self.assertEqual(status["top_up_due"]["amount"], 40000)
		self.assertEqual(frappe.db.get_value("Billing Profile", TEAM, "collection_mode"), "Auto Charge")
		self.assertFalse(
			frappe.db.exists("Billing Notification Log", {"team": TEAM, "event_type": "Action Required"})
		)

	def test_auto_charge_over_the_limit_only_before_the_wallet_sees_nothing(self):
		from central.billing.api.dashboard import account

		_set_mode("Auto Charge")
		credits.purchase(TEAM, 30000, "INR")
		with self._forecast(40000):
			status = account.get_collection_status(TEAM)

		self.assertFalse(status["action_required"])
		self.assertIsNone(status["top_up_due"])

	def test_a_team_in_action_required_sees_that_banner_not_the_top_up(self):
		from central.billing.api.dashboard import account

		_set_mode("Action Required")
		with self._forecast(40000):
			status = account.get_collection_status(TEAM)

		self.assertTrue(status["action_required"])
		self.assertIsNone(status["top_up_due"])

	@contextmanager
	def _forecast(self, total):
		with (
			self.freeze_time("2026-11-13 10:00:00"),
			patch(
				"central.billing.api.dashboard.invoices.get_forecast",
				return_value=_forecast_of(total),
			),
		):
			yield


class TestAnIssuedBill(TopUpTestCase):
	"""Credit added after issue pays the invoice only when it covers all of it."""

	def setUp(self):
		super().setUp()
		frappe.db.set_value("Billing Profile", TEAM, "payment_day", 8)
		self.invoice = _issued_invoice(TEAM, 40000, payment_date="2026-12-08")

	def test_a_top_up_that_leaves_the_rest_within_the_limit_does_not_stop_it(self):
		credits.purchase(TEAM, 25000, "INR")

		due = top_up_reminders.get_top_up_due(TEAM, "2026-12-03")

		self.assertEqual((due["amount"], due["invoice"]), (15000, self.invoice))

	def test_a_wallet_that_covers_the_invoice_stops_it(self):
		credits.purchase(TEAM, 40000, "INR")

		self.assertIsNone(top_up_reminders.get_top_up_due(TEAM, "2026-12-03"))

	def test_an_invoice_within_the_limit_is_not_reminded(self):
		frappe.db.set_value("Invoice", self.invoice, "expected_collection", 15000)

		self.assertIsNone(top_up_reminders.get_top_up_due(TEAM, "2026-12-03"))

	def test_no_payment_reminder_the_day_before_a_bill_over_the_limit(self):
		self.assertEqual(self._remind_day_before().get("skipped"), "top_up_notice")
		self.assertFalse(
			frappe.db.exists("Billing Notification Log", {"team": TEAM, "event_type": "Payment Reminder"})
		)

	def test_a_bill_within_the_limit_keeps_the_payment_reminder_path(self):
		frappe.db.set_value("Invoice", self.invoice, "expected_collection", 15000)

		self.assertNotEqual(self._remind_day_before().get("skipped"), "top_up_notice")

	def _remind_day_before(self) -> dict:
		from central.billing.payments import payment_notices

		with self.freeze_time("2026-12-07 10:00:00"):
			return payment_notices.send_payment_reminder(self.invoice, frappe.utils.now_datetime())


class TestLastMonthNotIssuedYet(TopUpTestCase):
	"""From the 1st to the payment date, the bill is last month's, even while it is held."""

	def setUp(self):
		super().setUp()
		frappe.db.set_value("Billing Profile", TEAM, "payment_day", 6)

	def test_a_held_draft_is_the_bill(self):
		_draft(TEAM, 30000, period_start="2026-11-01")

		self.assertEqual(self._run("2026-12-01"), [{"team": TEAM, "reminded": True}])
		self.assertIn("Add ₹ 30,000.00 of credit to your wallet by 6 December 2026.", _reminders()[0].message)

	def test_with_no_draft_last_month_is_projected(self):
		with patch.object(top_up_reminders, "get_forecast_total", return_value=20000) as forecast:
			due = top_up_reminders.get_top_up_due(TEAM, "2026-12-04")

		self.assertEqual((due["amount"], due["date"]), (20000, "2026-12-06"))
		self.assertEqual(forecast.call_args.args[1], frappe.utils.getdate("2026-11-01"))

	def test_after_the_payment_date_it_is_this_month(self):
		_draft(TEAM, 30000, period_start="2026-11-01")

		self.assertEqual(top_up_reminders.get_top_up_due(TEAM, "2026-12-07")["date"], "2027-01-06")


class TestExpiringCredit(TopUpTestCase):
	def test_promotional_credit_that_expires_before_the_payment_date_does_not_count(self):
		credits.grant_promotional_credits(TEAM, 10000, "INR", expires_on="2026-11-28")

		self.assertEqual(top_up_reminders.get_top_up_due(TEAM, REMINDER_DAYS[0])["amount"], 40000)

	def test_credit_still_valid_on_the_payment_date_counts(self):
		credits.grant_promotional_credits(TEAM, 10000, "INR", expires_on="2026-12-05")

		self.assertEqual(top_up_reminders.get_top_up_due(TEAM, REMINDER_DAYS[0])["amount"], 30000)


class TestHeldTeam(TopUpTestCase):
	def test_a_team_in_action_required_is_not_told_about_the_card_limit(self):
		_set_mode("Action Required")

		top_up_reminders.send_top_up_notice(
			TEAM, {"amount": 30000, "date": "2026-12-05", "limit": 15000.0, "has_method": True}
		)

		message = _reminders()[0].message
		self.assertIn(
			"Add ₹ 30,000.00 of credit to your wallet by 5 December 2026 to pay this bill.", message
		)
		self.assertNotIn("Your card or UPI", message)


def _draft(team: str, total, period_start: str = "2026-10-01") -> str:
	return (
		frappe.get_doc(
			{
				"doctype": "Invoice",
				"team": team,
				"invoice_type": "Billable",
				"status": "Outstanding",
				"period_start": period_start,
				"period_end": frappe.utils.get_last_day(period_start),
				"currency": "INR",
				"subtotal": total,
				"total": total,
				"expected_collection": total,
				"items": [
					{"resource_type": "bundle", "plan": "p", "rate": total, "days": 31, "amount": total}
				],
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _issued_invoice(team: str, total, payment_date: str) -> str:
	invoice = _draft(team, total)
	frappe.db.set_value("Invoice", invoice, {"due_date": payment_date, "payment_date": payment_date})
	return invoice
