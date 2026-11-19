# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""AI is billed at Grove's cost per model and landing day, converted at the month's rate."""

from unittest.mock import patch

import frappe

from central.billing.catalog.plan_setup import AI_PLAN, ensure_ai_plan
from central.billing.platform import readiness
from central.billing.revenue import exchange_rates, grove_bridge, service_reports, usage_recount
from central.billing.revenue.invoicing.generate import generate_team_invoice
from central.billing.revenue.usage_ledger import write_days
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import complete_billing_profile, ensure_team
from central.services import ai
from central.services.doctype.service.service import AI_SERVICE, STORAGE_SERVICE, ensure_services

TEAM_USD = "team-ai-billing-usd"
TEAM_INR = "team-ai-billing-inr"
JUNE = ("2026-06-01", "2026-06-30")


class FakeGrove:
	"""Answers a landing-window read with the cost each model landed for the team that day."""

	def __init__(self):
		self.landed: dict[tuple, dict] = {}
		self.failing: set[str] = set()

	def get_usage(self, teams, pulled_after=None, pulled_until=None, **_ignored):
		if teams[0] in self.failing:
			raise ConnectionError("Grove did not answer")
		costs = self.landed.get((teams[0], pulled_after[:10]), {})
		return {
			"model_summary": [
				{"model": model, "cost": cost, "requests": 1, "tokens": 10} for model, cost in costs.items()
			]
		}


def rate_on(day: str, rate: float = 84.1):
	return frappe._dict(rate=rate, rate_date=frappe.utils.getdate(day), source="rates.test")


def feed(rate):
	"""The rate API answers `rate`, or nothing when it is None."""
	return patch.object(exchange_rates, "feed_rate", return_value=rate)


def forget_rate_readings():
	"""Each test fakes its own rate API, so none may reuse another's cached reading."""
	frappe.cache.delete_keys(exchange_rates.READING_KEY)


def run_inline(method: str, queue=None, **kwargs):
	return frappe.get_attr(method)(**kwargs)


class AIBillingCase(IntegrationTestCase):
	"""A USD and an INR team on the AI plan, and a Grove that answers what each landed."""

	def setUp(self):
		ensure_ai_plan()
		ensure_services()
		bill_from = frappe.db.get_value("Service", AI_SERVICE, "bill_from")
		frappe.db.set_value("Service", AI_SERVICE, "bill_from", None)
		self.addCleanup(frappe.db.set_value, "Service", AI_SERVICE, "bill_from", bill_from)
		self.grove = FakeGrove()
		self.services = {TEAM_USD: self.ai_team(TEAM_USD, "USD"), TEAM_INR: self.ai_team(TEAM_INR, "INR")}
		forget_rate_readings()
		self.addCleanup(forget_rate_readings)
		# A rate kept by an earlier run would stand in for a month with none.
		frappe.db.delete("Monthly Exchange Rate", {"from_currency": "USD", "to_currency": "INR"})

	def ai_team(self, team: str, currency: str | None):
		frappe.db.delete("Team Service", {"team": team})
		self.addCleanup(frappe.db.delete, "Team Service", {"team": team})
		ensure_team(team)
		if currency:
			complete_billing_profile(team, currency=currency)
		service = frappe.get_doc(
			{
				"doctype": "Team Service",
				"team": team,
				"add_on_service": AI_SERVICE,
				"status": "Active",
				"external_id": team,
			}
		)
		service.subscribe_ai()
		service.db_insert()  # Skips before_insert, which registers the team at Grove.
		return service

	def land(self, team: str, day: str, costs: dict):
		self.grove.landed[(team, day)] = costs

	def read(self, *days: str, teams=None):
		subjects = grove_bridge.billed_subjects(AI_SERVICE, teams or list(self.services))
		with patch.object(grove_bridge.GroveClient, "from_settings", return_value=self.grove):
			write_days(grove_bridge.read_days(subjects, {team: list(days) for team in subjects}).rows)

	def days(self, team: str, **filters):
		return frappe.get_all(
			"Usage Day",
			filters={"team": team, **filters},
			fields=["day", "dimension", "quantity", "unit", "source_amount", "written_off", "invoice"],
			order_by="day asc, dimension asc",
		)

	def invoice_lines(self, team: str, period=JUNE):
		invoice = generate_team_invoice(team, *period)
		self.assertTrue(invoice, "the draft billed nothing")
		return frappe.get_all(
			"Invoice Line Item",
			filters={"parent": invoice, "resource_type": "AI Usage"},
			fields=["description", "quantity", "rate", "amount", "unit"],
			order_by="amount desc",
		)


class TestAIBilling(AIBillingCase):
	def test_each_model_is_its_own_day(self):
		self.land(TEAM_USD, "2026-06-10", {"claude-sonnet": 0.25, "gpt-4o": 1.5})
		self.read("2026-06-10")
		self.assertEqual(
			[(d.dimension, d.quantity, d.unit, d.source_amount) for d in self.days(TEAM_USD)],
			[("claude-sonnet", 0.25, "USD", 0.25), ("gpt-4o", 1.5, "USD", 1.5)],
		)

	def test_a_later_reading_of_a_landing_day_replaces_it(self):
		self.land(TEAM_USD, "2026-06-10", {"gpt-4o": 1.0})
		self.read("2026-06-10")
		self.land(TEAM_USD, "2026-06-10", {"gpt-4o": 2.5})
		self.read("2026-06-10")
		self.assertEqual([d.quantity for d in self.days(TEAM_USD)], [2.5])

	def test_one_team_that_fails_does_not_stop_the_page(self):
		self.land(TEAM_INR, "2026-06-10", {"gpt-4o": 1.0})
		self.land(TEAM_USD, "2026-06-10", {"gpt-4o": 1.0})
		self.grove.failing.add(TEAM_USD)
		with patch("frappe.log_error") as log_error:
			self.read("2026-06-10")
		self.assertEqual((len(self.days(TEAM_INR)), len(self.days(TEAM_USD))), (1, 0))
		self.assertIn("1 team(s) not read", log_error.call_args.kwargs["title"])

	def test_the_usd_invoice_bills_each_model_at_its_cost(self):
		self.land(TEAM_USD, "2026-06-10", {"gpt-4o": 3.0, "claude-sonnet": 1.25})
		self.land(TEAM_USD, "2026-06-11", {"gpt-4o": 0.5})
		self.read("2026-06-10", "2026-06-11")
		lines = self.invoice_lines(TEAM_USD)
		self.assertEqual(
			[(line.description, line.quantity, line.rate, line.amount, line.unit) for line in lines],
			[("gpt-4o", 3.5, 1, 3.5, "USD"), ("claude-sonnet", 1.25, 1, 1.25, "USD")],
		)
		self.assertTrue(all(d.invoice for d in self.days(TEAM_USD)))

	def test_a_correction_nets_against_its_model_and_a_model_below_zero_bills_no_line(self):
		# A correction is Grove's delta alone, recorded on the day it was resolved.
		self.land(TEAM_USD, "2026-06-10", {"gpt-4o": 4.0, "claude-sonnet": 0.5})
		self.land(TEAM_USD, "2026-06-12", {"gpt-4o": -1.0, "claude-sonnet": -2.0})
		self.read("2026-06-10", "2026-06-12")
		self.assertIn(-2.0, [d.quantity for d in self.days(TEAM_USD)])
		lines = self.invoice_lines(TEAM_USD)
		self.assertEqual([(line.description, line.amount) for line in lines], [("gpt-4o", 3.0)])
		self.assertFalse(any(d.invoice for d in self.days(TEAM_USD, dimension="claude-sonnet")))

	def test_an_inr_invoice_converts_at_the_months_rate(self):
		self.land(TEAM_INR, "2026-06-10", {"gpt-4o": 2.0})
		self.read("2026-06-10")
		with feed(rate_on("2026-06-01")):
			[line] = self.invoice_lines(TEAM_INR)
		self.assertEqual((line.quantity, line.rate, line.amount), (2.0, 84.1, 168.2))
		self.assertIn("rate of 2026-06-01", line.description)
		self.assertEqual(
			frappe.db.get_value(
				"Monthly Exchange Rate",
				{"month": "2026-06-01", "from_currency": "USD", "to_currency": "INR"},
				"rate",
			),
			84.1,
		)

	def test_a_stored_month_rate_is_kept_when_the_rate_api_changes(self):
		with feed(rate_on("2026-06-01", 84.1)):
			exchange_rates.fix_month_rate("USD", "INR", "2026-06-15")
		with feed(rate_on("2026-06-01", 90)):
			self.assertEqual(exchange_rates.month_rate("USD", "INR", "2026-06-20").rate, 84.1)

	def test_a_rate_for_the_first_dated_earlier_is_used_and_its_date_printed(self):
		# On a holiday the API gives the last working day's rate for the 1st.
		self.land(TEAM_INR, "2026-06-10", {"gpt-4o": 1.0})
		self.read("2026-06-10")
		with feed(rate_on("2026-05-29", 83.5)):
			[line] = self.invoice_lines(TEAM_INR)
		self.assertEqual(line.rate, 83.5)
		self.assertIn("rate of 2026-05-29", line.description)
		stored = exchange_rates.stored_rate(exchange_rates.month_key("USD", "INR", "2026-06-01"))
		self.assertEqual((stored.rate, str(stored.rate_date)), (83.5, "2026-05-29"))
		self.assertEqual(self.inr_rollup_rate(), (83.5, "2026-05-29"))

	def test_with_the_rate_api_down_the_draft_uses_last_months_kept_rate(self):
		keep_rate("2026-05-01", 83.0)
		self.land(TEAM_INR, "2026-06-10", {"gpt-4o": 1.0})
		self.read("2026-06-10")
		with feed(None):
			[line] = self.invoice_lines(TEAM_INR)
		self.assertEqual(line.rate, 83.0)
		self.assertIn("rate of 2026-05-01", line.description)
		stored = frappe.db.get_value(
			"Monthly Exchange Rate", {"month": "2026-06-01", "to_currency": "INR"}, ["rate_date", "source"]
		)
		self.assertEqual((str(stored[0]), stored[1]), ("2026-05-01", "fallback: 2026-05"))
		self.assertEqual(self.inr_rollup_rate(), (83.0, "2026-05-01"))

	def test_an_unstored_reading_is_reused_for_an_hour_but_a_stored_rate_is_read_each_time(self):
		with feed(rate_on("2026-05-29", 83.5)) as read:
			exchange_rates.month_rate("USD", "INR", "2026-06-10")
			found = exchange_rates.month_rate("USD", "INR", "2026-06-20")
		self.assertEqual((found.rate, read.call_count), (83.5, 1))
		# The draft's final read asks the rate API again and stores what it gives now.
		with feed(rate_on("2026-06-01", 84.1)):
			exchange_rates.fix_month_rate("USD", "INR", "2026-06-01", final=True)
		self.assertEqual(exchange_rates.month_rate("USD", "INR", "2026-06-20").rate, 84.1)

	def test_with_no_rate_ever_kept_the_inr_draft_fails(self):
		self.land(TEAM_INR, "2026-06-10", {"gpt-4o": 1.0})
		self.read("2026-06-10")
		with feed(None), self.assertRaises(frappe.ValidationError):
			generate_team_invoice(TEAM_INR, *JUNE)

	def inr_rollup_rate(self):
		rollup = frappe.get_all(
			"Usage Rollup", filters={"team": TEAM_INR}, fields=["locked_rate", "rate_date"]
		)[0]
		return (rollup.locked_rate, str(rollup.rate_date))

	def test_usage_before_billing_starts_is_kept_written_off(self):
		frappe.db.set_value("Service", AI_SERVICE, "bill_from", "2026-06-15")
		self.land(TEAM_USD, "2026-06-10", {"gpt-4o": 5.0})
		self.land(TEAM_USD, "2026-06-20", {"gpt-4o": 2.0})
		self.read("2026-06-10", "2026-06-20")
		self.assertEqual([(d.quantity, d.written_off) for d in self.days(TEAM_USD)], [(5.0, 1), (2.0, 0)])
		[line] = self.invoice_lines(TEAM_USD)
		self.assertEqual(line.amount, 2.0)
		self.assertFalse(self.days(TEAM_USD, written_off=1)[0].invoice)

	def test_the_backfill_stores_the_days_before_billing_written_off(self):
		frappe.db.set_value("Service", AI_SERVICE, "bill_from", "2026-06-03")
		self.land(TEAM_USD, "2026-06-01", {"gpt-4o": 1.0})
		self.land(TEAM_USD, "2026-06-02", {"gpt-4o": 2.0})
		self.land(TEAM_USD, "2026-06-03", {"gpt-4o": 4.0})
		with patch.object(grove_bridge.GroveClient, "from_settings", return_value=self.grove):
			grove_bridge.backfill("2026-06-01")
		self.assertEqual([(d.quantity, d.written_off) for d in self.days(TEAM_USD)], [(1.0, 1), (2.0, 1)])
		# Explicit days: where the hourly reading starts is not moved.
		self.assertFalse(
			frappe.db.get_value("Team Service", self.services[TEAM_USD].name, "usage_read_until")
		)

	def test_the_hourly_recount_writes_one_rollup_per_model(self):
		self.land(TEAM_USD, "2026-06-10", {"gpt-4o": 3.0, "claude-sonnet": 1.0})
		self.read("2026-06-10")
		with patch("frappe.enqueue", side_effect=run_inline):
			usage_recount.recount_changed()
		rollups = frappe.get_all(
			"Usage Rollup",
			filters={"team": TEAM_USD, "resource_type": "AI Usage"},
			fields=["dimension", "quantity", "locked_rate", "cluster"],
			order_by="dimension asc",
		)
		self.assertEqual(
			[(r.dimension, r.quantity, r.locked_rate, r.cluster or None) for r in rollups],
			[("claude-sonnet", 1.0, 1, None), ("gpt-4o", 3.0, 1, None)],
		)

	def test_ai_is_subscribed_once_the_team_has_a_billing_currency(self):
		self.assertEqual(
			frappe.db.get_value("Subscription", self.services[TEAM_USD].subscription, "plan"), AI_PLAN
		)
		later = "team-ai-billing-later"
		service = self.ai_team(later, None)
		self.assertFalse(service.subscription)
		service.validate()  # An AI service may wait for a currency without a subscription.
		complete_billing_profile(later, currency="USD")
		grove_bridge.subscribe_ai_teams()
		self.assertTrue(frappe.db.get_value("Team Service", service.name, "subscription"))

	def test_a_report_may_carry_the_model_and_a_negative_cost(self):
		ai_service = frappe.get_doc("Service", AI_SERVICE)
		subjects = {TEAM_USD: self.services[TEAM_USD]}
		line = {"subject": TEAM_USD, "meter": "cost", "day": "2026-06-10", "value": -5, "dimension": "gpt-4o"}
		self.assertIsNone(service_reports.line_problem(ai_service, line, subjects))
		self.assertTrue(service_reports.line_problem(ai_service, {**line, "dimension": "x" * 141}, subjects))
		storage = frappe.get_doc("Service", STORAGE_SERVICE)
		bucket_line = {**line, "meter": "bytes_stored", "dimension": None}
		self.assertIn("from 0", service_reports.line_problem(storage, bucket_line, subjects))

	def test_the_overview_shows_an_inr_team_the_months_rate_without_storing_it(self):
		self.assertIsNone(ai.get_billing_rate(TEAM_USD))
		# A team with no billing currency is not billed, so it is not shown rupees either.
		self.assertIsNone(ai.get_billing_rate("team-ai-billing-no-profile"))
		with feed(rate_on("2026-06-01")):
			found = ai.get_billing_rate(TEAM_INR)
		self.assertEqual((found["currency"], found["rate"]), ("INR", 84.1))
		self.assertFalse(frappe.db.count("Monthly Exchange Rate", {"rate_date": "2026-06-01"}))
		forget_rate_readings()
		with feed(None):
			self.assertIsNone(ai.get_billing_rate(TEAM_INR))

	def test_readiness_reports_a_billing_currency_with_no_usd_rate(self):
		with feed(None):
			self.assertIn("INR", [v.subject for v in readiness.check_converted_usage_has_a_rate()])
		with feed(rate_on("2026-06-01")):
			self.assertEqual(readiness.check_converted_usage_has_a_rate(), [])

	def test_with_the_rate_api_down_an_earlier_kept_rate_satisfies_readiness(self):
		earlier = frappe.utils.add_months(readiness_month(), -2)
		keep_rate(earlier, 83.0)
		with feed(None):
			self.assertEqual(readiness.check_converted_usage_has_a_rate(), [])


def keep_rate(month, rate: float):
	"""Keep a USD to INR rate for `month`, dated its 1st, as an earlier draft would have."""
	frappe.get_doc(
		{
			"doctype": "Monthly Exchange Rate",
			"month": month,
			"from_currency": "USD",
			"to_currency": "INR",
			"rate": rate,
			"rate_date": month,
			"source": "rates.test",
		}
	).insert(ignore_permissions=True)


def readiness_month():
	from central.billing.revenue.usage_ledger import utc_today

	return utc_today().replace(day=1)
