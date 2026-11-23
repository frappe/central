# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""AI billing across days and months: when the rate is kept, credits carry, and reading catches up."""

import datetime
from unittest.mock import patch

import frappe

from central.billing.api.dashboard._shared import _describe_line
from central.billing.revenue import exchange_rates, grove_bridge, usage_recount
from central.billing.revenue.invoicing.generate import team_clusters
from central.billing.revenue.metered_lines import MAXIMUM_DESCRIPTION, line_description
from central.billing.revenue.metering import metered_line_items_for_clusters
from central.billing.tests.test_ai_billing import (
	JUNE,
	TEAM_INR,
	TEAM_USD,
	AIBillingCase,
	feed,
	forget_rate_readings,
	keep_rate,
	rate_on,
	run_inline,
)
from central.services.doctype.service.service import AI_SERVICE

JULY = ("2026-07-01", "2026-07-31")
AUGUST = ("2026-08-01", "2026-08-31")


class TestAIBillingMonths(AIBillingCase):
	def recount(self, rate, today: str = "2026-07-01"):
		# Each recount stands for a later hour, after the cached reading has expired.
		forget_rate_readings()
		with (
			feed(rate),
			patch.object(exchange_rates, "utc_today", return_value=frappe.utils.getdate(today)),
			patch("frappe.enqueue", side_effect=run_inline),
		):
			usage_recount.recount_changed()

	def inr_rollup(self):
		return frappe.get_all(
			"Usage Rollup",
			filters={"team": TEAM_INR, "resource_type": "AI Usage", "superseded_by": ["is", "not set"]},
			fields=["name", "locked_rate", "rate_date"],
		)[0]

	def test_the_recount_keeps_the_rate_unlocked_on_the_first_and_locks_it_from_the_second(self):
		self.land(TEAM_INR, "2026-06-01", {"gpt-4o": 2.0})
		self.read("2026-06-01")
		# On the 1st the API may still give the last day's rate.
		self.recount(rate_on("2026-05-29", 83.5), today="2026-06-01")
		rollup = self.inr_rollup()
		self.assertEqual((rollup.locked_rate, rollup.rate_date), (83.5, None))
		self.assertFalse(frappe.db.count("Monthly Exchange Rate", {"month": "2026-06-01"}))

		self.land(TEAM_INR, "2026-06-02", {"gpt-4o": 1.0})
		self.read("2026-06-02")
		self.recount(rate_on("2026-06-01", 84.1), today="2026-06-02")
		rollup = self.inr_rollup()
		self.assertEqual((rollup.locked_rate, str(rollup.rate_date)), (84.1, "2026-06-01"))

		# Locked: a later change in the rate API does not move it.
		self.land(TEAM_INR, "2026-06-12", {"gpt-4o": 1.0})
		self.read("2026-06-12")
		self.recount(rate_on("2026-06-01", 90), today="2026-06-12")
		self.assertEqual(self.inr_rollup().locked_rate, 84.1)

	def test_an_earlier_months_rate_is_not_kept_before_the_draft(self):
		keep_rate("2026-05-01", 83.0)
		self.land(TEAM_INR, "2026-06-10", {"gpt-4o": 2.0})
		self.read("2026-06-10")
		self.recount(None, today="2026-06-10")
		rollup = self.inr_rollup()
		self.assertEqual((rollup.locked_rate, rollup.rate_date), (83.0, None))
		self.assertFalse(frappe.db.count("Monthly Exchange Rate", {"month": "2026-06-01"}))

	def test_the_draft_keeps_the_rate_on_the_first(self):
		with (
			feed(rate_on("2026-05-29", 83.5)),
			patch.object(exchange_rates, "utc_today", return_value=frappe.utils.getdate("2026-06-01")),
		):
			self.assertFalse(exchange_rates.fix_month_rate("USD", "INR", "2026-06-01").fixed)
			self.assertTrue(exchange_rates.fix_month_rate("USD", "INR", "2026-06-01", final=True).fixed)

	def test_a_worker_that_loses_the_race_returns_the_stored_rate(self):
		key = exchange_rates.month_key("USD", "INR", "2026-06-01")
		with feed(rate_on("2026-06-01", 84.1)):
			exchange_rates.fix_month_rate("USD", "INR", "2026-06-01")
		found = exchange_rates._store(key, frappe._dict(rate_on("2026-06-01", 90), fixed=False))
		self.assertEqual((found.rate, found.fixed), (84.1, True))

	def test_a_race_whose_winner_rolled_back_keeps_the_reading_unstored(self):
		key = exchange_rates.month_key("USD", "INR", "2026-06-01")
		with feed(rate_on("2026-06-01", 84.1)):
			exchange_rates.fix_month_rate("USD", "INR", "2026-06-01")
		get_value = frappe.db.get_value

		def winner_gone(*args, **kwargs):
			return None if kwargs.get("for_update") else get_value(*args, **kwargs)

		reading = frappe._dict(rate_on("2026-06-01", 90), fixed=False)
		with patch.object(frappe.db, "get_value", side_effect=winner_gone):
			found = exchange_rates._store(key, reading)
		self.assertEqual((found.rate, found.fixed), (90, False))

	def test_a_model_below_zero_carries_its_credit_into_its_next_months(self):
		self.land(TEAM_USD, "2026-06-10", {"gpt-4o": 4.0, "claude-sonnet": 0.5})
		self.land(TEAM_USD, "2026-06-12", {"claude-sonnet": -2.0})
		self.land(TEAM_USD, "2026-07-05", {"gpt-4o": 1.0, "claude-sonnet": 1.0})
		self.land(TEAM_USD, "2026-08-05", {"gpt-4o": 1.0, "claude-sonnet": 2.0})
		self.read("2026-06-10", "2026-06-12", "2026-07-05", "2026-08-05")

		self.assertEqual(
			[(li.description, li.amount) for li in self.invoice_lines(TEAM_USD)], [("gpt-4o", 4.0)]
		)
		# July nets -0.5 for the model, so it is still a credit and carries on.
		self.assertEqual(
			[(li.description, li.amount) for li in self.invoice_lines(TEAM_USD, JULY)], [("gpt-4o", 1.0)]
		)
		august = self.invoice_lines(TEAM_USD, AUGUST)
		self.assertEqual(
			[(li.description, li.amount) for li in august], [("claude-sonnet", 1.5), ("gpt-4o", 1.0)]
		)
		claude = self.days(TEAM_USD, dimension="claude-sonnet")
		self.assertEqual(len({d.invoice for d in claude}), 1, "each credit day is billed once, in August")
		self.assertTrue(all(d.invoice for d in claude))

	def test_each_team_is_read_from_where_it_was_last_read(self):
		service = self.services[TEAM_USD].name
		frappe.db.set_value("Team Service", service, "usage_read_until", "2026-06-10")
		for day, cost in (("2026-06-10", 1.0), ("2026-06-11", 2.0), ("2026-06-12", 4.0)):
			self.land(TEAM_USD, day, {"gpt-4o": cost})
		self.read_page("2026-06-12", TEAM_USD)
		self.assertEqual([d.quantity for d in self.days(TEAM_USD)], [1.0, 2.0, 4.0])
		self.assertEqual(str(frappe.db.get_value("Team Service", service, "usage_read_until")), "2026-06-12")

	def test_a_team_never_read_starts_at_bill_from_and_catches_up_a_week_a_run(self):
		frappe.db.set_value("Service", AI_SERVICE, "bill_from", "2026-06-01")
		service = self.services[TEAM_USD].name
		frappe.db.set_value("Team Service", service, "creation", "2026-05-01 10:00:00")
		for day in range(1, 13):
			self.land(TEAM_USD, f"2026-06-{day:02}", {"gpt-4o": 1.0})
		self.read_page("2026-06-12", TEAM_USD)
		self.assertEqual(str(frappe.db.get_value("Team Service", service, "usage_read_until")), "2026-06-07")
		self.read_page("2026-06-12", TEAM_USD)
		self.assertEqual(len(self.days(TEAM_USD)), 12)
		self.assertEqual(str(frappe.db.get_value("Team Service", service, "usage_read_until")), "2026-06-12")

	def test_a_team_that_fails_keeps_its_read_day(self):
		for team in (TEAM_USD, TEAM_INR):
			frappe.db.set_value("Team Service", self.services[team].name, "usage_read_until", "2026-06-11")
			self.land(team, "2026-06-12", {"gpt-4o": 1.0})
		# A model name the monthly rollup key cannot hold fails its team, not the page:
		# cutting it could merge two models.
		self.land(TEAM_INR, "2026-06-12", {"x" * (self.model_room() + 1): 1.0})
		with patch("frappe.log_error") as log_error:
			self.read_page("2026-06-12", TEAM_USD, TEAM_INR)
		self.assertIn("1 team(s) not read", log_error.call_args.kwargs["title"])
		self.assertEqual((len(self.days(TEAM_USD)), len(self.days(TEAM_INR))), (1, 0))
		read_until = frappe.db.get_value("Team Service", self.services[TEAM_INR].name, "usage_read_until")
		self.assertEqual(str(read_until), "2026-06-11")

	def test_a_model_name_that_just_fits_the_rollup_key_is_billed(self):
		room = self.model_room()
		self.assertLess(room, grove_bridge.MAXIMUM_DIMENSION)
		frappe.db.set_value("Team Service", self.services[TEAM_INR].name, "usage_read_until", "2026-06-11")
		self.land(TEAM_INR, "2026-06-12", {"x" * room: 1.0})
		self.read_page("2026-06-12", TEAM_INR)
		self.recount(rate_on("2026-06-01"))
		self.assertTrue(frappe.db.exists("Usage Rollup", {"team": TEAM_INR, "dimension": "x" * room}))

	def model_room(self):
		subject = frappe.db.get_value("Subscription", self.services[TEAM_INR].subscription, "service_subject")
		return usage_recount.dimension_room(AI_SERVICE, subject)

	def test_forecasts_and_rerating_see_ai_but_no_other_blank_cluster_usage(self):
		self.land(TEAM_USD, "2026-06-10", {"gpt-4o": 3.0})
		self.read("2026-06-10")
		self.recount(None)
		frappe.get_doc(
			{
				"doctype": "Usage Rollup",
				"team": TEAM_USD,
				"resource_id": "tokens-subject",
				"resource_type": "Tokens",
				"period_start": "2026-06-01",
				"period_end": "2026-06-30",
				"quantity": 5,
				"currency": "USD",
				"locked_rate": 1,
				"idempotency_key": "test-ai-billing-tokens",
			}
		).insert(ignore_permissions=True)
		lines = metered_line_items_for_clusters(TEAM_USD, team_clusters(TEAM_USD), *JUNE)
		self.assertEqual([(li["resource_type"], li["amount"]) for li in lines], [("AI Usage", 3.0)])

	def test_a_long_model_keeps_the_rate_in_the_line_description(self):
		rollup = frappe._dict(
			dimension="m" * 140, rate_date=datetime.date(2026, 6, 1), unit="USD", currency="INR"
		)
		description = line_description(rollup, 84.1)
		self.assertLessEqual(len(description), MAXIMUM_DESCRIPTION)
		self.assertTrue(description.endswith("rate of 2026-06-01"))

	def test_the_customer_invoice_shows_the_model_and_rate(self):
		line = frappe._dict(
			resource_type="AI Usage", quantity=2, unit="USD", rate=84.1, amount=168.2, description="gpt-4o"
		)
		self.assertTrue(_describe_line(TEAM_USD, line, JUNE)["detail"].endswith(" · gpt-4o"))

	def read_page(self, today: str, *teams: str):
		with (
			patch.object(grove_bridge, "utc_today", return_value=frappe.utils.getdate(today)),
			patch.object(grove_bridge.GroveClient, "from_settings", return_value=self.grove),
		):
			grove_bridge.read_page(list(teams))
