# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The patch folds Usage Days and recounted rollups into month rows, and the invoices stay the same."""

import datetime
from unittest.mock import patch

import frappe

from central.billing.doctype.billing_run_team.billing_run_team import INVOICED, record_outcome
from central.billing.revenue import usage_fold, usage_recount
from central.billing.revenue.invoicing.generate import team_clusters
from central.billing.revenue.metering import metered_line_items_for_clusters
from central.billing.revenue.usage_evidence import DayEvidence, check_days_carry_a_derivation
from central.billing.tests.test_ai_billing import TEAM_INR, TEAM_USD, AIBillingCase, feed, rate_on
from central.billing.tests.utils import BillingTestCase, usage_days
from central.patches.v0_0 import count_underived_days_from_now, fold_usage_days_into_months
from central.services.doctype.service.service import AI_METER, AI_SERVICE

JUNE = ("2026-06-01", "2026-06-30")
JULY = ("2026-07-01", "2026-07-31")
INVOICES = {TEAM_INR: "fold-june-inr", TEAM_USD: "fold-june-usd"}
# What the day ledger kept before the fold: (team, day, model, USD, billed).
DAYS = (
	(TEAM_INR, "2026-06-10", "gpt-4o", 2.0, True),
	(TEAM_INR, "2026-06-10", "claude-sonnet", 0.5, False),
	(TEAM_INR, "2026-06-12", "claude-sonnet", -1.0, False),
	(TEAM_USD, "2026-06-11", "gpt-4o", 3.0, True),
	(TEAM_INR, "2026-07-05", "gpt-4o", 1.0, False),
	(TEAM_INR, "2026-07-05", "claude-sonnet", 1.0, False),
	(TEAM_USD, "2026-07-06", "gpt-4o", 4.0, False),
)
# And the rollups its recount wrote: (team, month, model, quantity, rate, rate date, billed). June's
# claude month was below zero, so it was not billed and its days were carried into July's.
ROLLUPS = (
	(TEAM_INR, "2026-06-01", "gpt-4o", 2.0, 84.1, "2026-06-01", True),
	(TEAM_INR, "2026-06-01", "claude-sonnet", -0.5, 84.1, "2026-06-01", False),
	(TEAM_USD, "2026-06-01", "gpt-4o", 3.0, 1.0, None, True),
	(TEAM_INR, "2026-07-01", "gpt-4o", 1.0, 85.0, None, False),
	(TEAM_INR, "2026-07-01", "claude-sonnet", 0.5, 85.0, None, False),
	(TEAM_USD, "2026-07-01", "gpt-4o", 4.0, 1.0, None, False),
)


class TestFoldUsageDays(AIBillingCase):
	def setUp(self):
		super().setUp()
		for key in (usage_fold.WATERMARK, usage_recount.WATERMARK):
			self.addCleanup(frappe.db.set_default, key, frappe.db.get_default(key))
		self.addCleanup(frappe.db.delete, "Billing Run Team", {"team": ["in", list(INVOICES)]})
		meter = frappe.get_doc("Service", AI_SERVICE).get_meter(AI_METER)
		for team, day, model, cost, billed in DAYS:
			self.insert_day(meter, team, day, model, cost, billed)
		for rollup in ROLLUPS:
			self.insert_rollup(*rollup)
		# June's draft kept the month's rate, as the rate its INR rollup names.
		frappe.get_doc(
			{
				"doctype": "Monthly Exchange Rate",
				"month": JUNE[0],
				"from_currency": "USD",
				"to_currency": "INR",
				"rate": 84.1,
				"rate_date": JUNE[0],
				"source": "rates.test",
			}
		).insert(ignore_permissions=True)
		# An operator re-priced June's USD month: the old version points at the one that is billed.
		self.reprice(TEAM_USD, "2026-06-01", "gpt-4o", rate=0.9)

	def insert_day(self, meter, team: str, day: str, model: str, cost: float, billed: bool) -> None:
		row = meter.get_day_row(
			self.services[team], day, cost * frappe.utils.flt(meter.unit_divisor), dimension=model
		)
		as_of = frappe.utils.get_datetime(f"{day} 23:00:00")
		invoice = INVOICES[team] if billed else None
		frappe.get_doc(
			{"doctype": "Usage Day", **row, "as_of": as_of, "landed_at": as_of, "invoice": invoice}
		).db_insert()

	def insert_rollup(
		self, team: str, month: str, model: str, quantity: float, rate, rate_date, billed
	) -> None:
		subscription = self.services[team].subscription
		subject, cluster = frappe.db.get_value("Subscription", subscription, ["service_subject", "cluster"])
		month = frappe.utils.getdate(month)
		frappe.get_doc(
			{
				"doctype": "Usage Rollup",
				"idempotency_key": f"{AI_SERVICE}::{subject}::{month:%Y-%m}::{model}",
				"resource_id": subject,
				"resource_type": "AI Usage",
				"dimension": model,
				"meter_type": "Counter",
				"team": team,
				"cluster": cluster,
				"currency": frappe.db.get_value("Billing Profile", {"team": team}, "currency"),
				"period_start": month,
				"period_end": frappe.utils.get_last_day(month),
				"quantity": quantity,
				"unit": "USD",
				"locked_allowance": 0,
				"locked_rate": rate,
				"rate_date": rate_date,
				"invoice": INVOICES[team] if billed else None,
			}
		).db_insert()

	def reprice(self, team: str, month: str, model: str, rate: float) -> None:
		old = frappe.get_doc("Usage Rollup", {"team": team, "period_start": month, "dimension": model})
		new = frappe.copy_doc(old)
		new.update({"locked_rate": rate, "idempotency_key": f"{old.idempotency_key}::v1"})
		new.db_insert()
		frappe.db.set_value("Usage Rollup", old.name, "superseded_by", new.name)

	def lines(self) -> list:
		return sorted(
			(team, period[0], line["resource_type"], line["dimension"], line["quantity"], line["amount"])
			for team in (TEAM_INR, TEAM_USD)
			for period in (JUNE, JULY)
			for line in metered_line_items_for_clusters(team, team_clusters(team), *period)
		)

	def days(self) -> list:
		return sorted(
			(day.team, str(day.day), day.dimension, day.quantity, bool(day.invoice))
			for team in (TEAM_INR, TEAM_USD)
			for day in usage_days(team=team)
		)

	def test_the_patch_keeps_every_metered_line_and_day(self):
		# Read from the day ledger's rollups, as before the patch.
		lines = self.lines()
		self.assertEqual(
			[(team, month, model, amount) for team, month, _type, model, _quantity, amount in lines],
			[
				(TEAM_INR, "2026-06-01", "gpt-4o", 168.2),
				(TEAM_INR, "2026-07-01", "claude-sonnet", 42.5),
				(TEAM_INR, "2026-07-01", "gpt-4o", 85.0),
				(TEAM_USD, "2026-06-01", "gpt-4o", 2.7),
				(TEAM_USD, "2026-07-01", "gpt-4o", 4.0),
			],
		)

		fold_usage_days_into_months.execute()

		self.assertEqual(self.lines(), lines)
		self.assertEqual(
			self.days(), sorted((team, day, model, cost, billed) for team, day, model, cost, billed in DAYS)
		)
		self.assertFalse(usage_fold.ledger_rollups())
		self.assertTrue(frappe.db.count("Usage Day"), "the old days stay, read only")

	def test_a_billed_month_bills_nothing_again_after_the_patch(self):
		for team in INVOICES:
			record_outcome(team, JUNE[1], INVOICED)
		fold_usage_days_into_months.execute()
		# Recounting June moves its carried claude days on to July, which reads July's rate.
		with feed(rate_on("2026-07-01", 85.0)):
			for team, invoice in INVOICES.items():
				self.assertEqual(usage_recount.recount_team(team, JUNE[1]).months, [])
				billed = [
					day.invoice for day in usage_days(team=team, month=JUNE[0]) if day.dimension == "gpt-4o"
				]
				self.assertEqual(set(billed), {invoice})
			july = self.invoice_lines(TEAM_INR, JULY)
		# Claude nets -0.5 in June and +1.0 in July: only July and that carry are billed.
		self.assertEqual(
			[(line.description.split(" · ")[0], line.amount) for line in july],
			[("gpt-4o", 85.0), ("claude-sonnet", 42.5)],
		)

	def test_each_folded_day_names_a_migrated_report(self):
		fold_usage_days_into_months.execute()
		reports = {day.report for day in usage_days(team=TEAM_INR)}
		self.assertEqual(
			{frappe.db.get_value("Usage Report", name, "kind") for name in reports}, {"Migrated"}
		)

	def test_a_day_an_older_worker_writes_after_the_patch_is_folded_on_the_next_recount(self):
		fold_usage_days_into_months.execute()
		meter = frappe.get_doc("Service", AI_SERVICE).get_meter(AI_METER)
		self.insert_day(meter, TEAM_USD, "2026-07-07", "gpt-4o", 2.0, billed=False)
		usage_fold.fold_stragglers()
		self.assertIn(
			(datetime.date(2026, 7, 7), 2.0), [(d.day, d.quantity) for d in usage_days(team=TEAM_USD)]
		)

	def test_a_folded_straggler_carries_its_migrated_derivation(self):
		fold_usage_days_into_months.execute()
		count_underived_days_from_now.execute()
		meter = frappe.get_doc("Service", AI_SERVICE).get_meter(AI_METER)
		self.insert_day(meter, TEAM_USD, "2026-07-07", "gpt-4o", 2.0, billed=False)
		usage_fold.fold_stragglers()
		found = [v for v in check_days_carry_a_derivation("2026-07-10") if v.subject == AI_SERVICE]
		self.assertEqual(found, [])
		[day] = [d for d in usage_days(team=TEAM_USD) if d.day == datetime.date(2026, 7, 7)]
		answer = DayEvidence.of(day.month_row, 7)
		self.assertEqual((answer["derived"], answer["derivation"]), (True, {"kind": "Migrated"}))


class TestFoldWatermark(BillingTestCase):
	def test_the_watermark_is_the_moment_before_the_days_were_read(self):
		self.addCleanup(
			frappe.db.set_default, usage_fold.WATERMARK, frappe.db.get_default(usage_fold.WATERMARK)
		)
		start = frappe.utils.now_datetime()
		clock = {"now": start}
		read_rollups = usage_fold.ledger_rollups

		def rollups_an_hour_later(*args, **kwargs):
			# The days are read by now; a day written from here on is newer than the watermark.
			clock["now"] = start + datetime.timedelta(hours=1)
			return read_rollups(*args, **kwargs)

		with (
			patch("frappe.utils.now_datetime", side_effect=lambda: clock["now"]),
			patch.object(usage_fold, "ledger_rollups", side_effect=rollups_an_hour_later),
		):
			usage_fold.fold_all()

		self.assertEqual(frappe.db.get_default(usage_fold.WATERMARK), str(start))
