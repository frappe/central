# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The patch folds Usage Days and recounted rollups into month rows, and the invoices stay the same."""

import calendar
import datetime
from unittest.mock import patch

import frappe

from central.billing.revenue import usage_fold, usage_recount
from central.billing.revenue.invoicing.generate import team_clusters
from central.billing.revenue.metering import metered_line_items_for_clusters
from central.billing.revenue.usage_month import day_rows
from central.billing.tests.test_ai_billing import (
	TEAM_INR,
	TEAM_USD,
	AIBillingCase,
	feed,
	forget_rate_readings,
	rate_on,
	run_inline,
)
from central.billing.tests.utils import BillingTestCase, usage_days
from central.patches.v0_0 import fold_usage_days_into_months

JUNE = ("2026-06-01", "2026-06-30")
JULY = ("2026-07-01", "2026-07-31")
_DAY_FIELDS = (
	"service",
	"meter",
	"subject",
	"dimension",
	"day",
	"aggregation",
	"team",
	"subscription",
	"resource_type",
	"quantity",
	"included",
	"unit",
	"source_amount",
	"source_currency",
	"as_of",
	"landed_at",
	"estimated",
	"written_off",
	"invoice",
)


def unfold() -> None:
	"""Turn the month rows into the Usage Days and recounted rollups the day ledger kept."""
	months = frappe.get_all("Usage Month", fields=["*"])
	for month in months:
		for day in day_rows({"name": month.name}):
			frappe.get_doc({"doctype": "Usage Day", **{name: day[name] for name in _DAY_FIELDS}}).db_insert()
		if month.counted_at:
			frappe.get_doc(_rollup_of(month)).db_insert()
	frappe.db.delete("Usage Month", {"name": ["in", [month.name for month in months]]})


def _rollup_of(month) -> dict:
	key = f"{month.service}::{month.resource_id}::{month.month:%Y-%m}"
	last = calendar.monthrange(month.month.year, month.month.month)[1]
	return {
		"doctype": "Usage Rollup",
		"idempotency_key": f"{key}::{month.dimension}" if month.dimension else key,
		"resource_id": month.resource_id,
		"resource_type": month.resource_type,
		"dimension": month.dimension,
		"meter_type": "Gauge" if month.aggregation == "Level" else "Counter",
		"team": month.team,
		"cluster": month.cluster,
		"currency": month.currency,
		"period_start": month.month,
		"period_end": month.month.replace(day=last),
		"quantity": month.quantity,
		"unit": month.unit,
		"locked_allowance": month.locked_allowance,
		"locked_rate": month.locked_rate,
		"rate_date": month.rate_date,
		"invoice": month.invoice,
	}


class TestFoldUsageDays(AIBillingCase):
	def setUp(self):
		super().setUp()
		for key in (usage_fold.WATERMARK, usage_recount.WATERMARK):
			self.addCleanup(frappe.db.set_default, key, frappe.db.get_default(key))
		# June: two models, one below zero, billed. July: open.
		self.land(TEAM_INR, "2026-06-10", {"gpt-4o": 2.0, "claude-sonnet": 0.5})
		self.land(TEAM_INR, "2026-06-12", {"claude-sonnet": -1.0})
		self.land(TEAM_USD, "2026-06-11", {"gpt-4o": 3.0})
		self.land(TEAM_INR, "2026-07-05", {"gpt-4o": 1.0, "claude-sonnet": 1.0})
		self.land(TEAM_USD, "2026-07-06", {"gpt-4o": 4.0})
		self.read("2026-06-10", "2026-06-11", "2026-06-12", "2026-07-05", "2026-07-06")
		with feed(rate_on("2026-06-01", 84.1)):
			for team in (TEAM_INR, TEAM_USD):
				self.invoice_lines(team)
		self.invoices = {
			team: frappe.db.get_value("Invoice", {"team": team, "period_start": JUNE[0]})
			for team in (TEAM_INR, TEAM_USD)
		}
		forget_rate_readings()
		frappe.db.set_default(usage_recount.WATERMARK, "2000-01-01 00:00:00")
		with feed(rate_on("2026-07-01", 85.0)), patch("frappe.enqueue", side_effect=run_inline):
			usage_recount.recount_changed()

	def lines(self) -> list:
		return sorted(
			(team, period[0], line["resource_type"], line["dimension"], line["quantity"], line["amount"])
			for team in (TEAM_INR, TEAM_USD)
			for period in (JUNE, JULY)
			for line in metered_line_items_for_clusters(team, team_clusters(team), *period)
		)

	def days(self) -> list:
		return [
			(day.team, day.day, day.dimension, day.quantity, day.invoice, day.subscription)
			for team in (TEAM_INR, TEAM_USD)
			for day in usage_days(team=team)
		]

	def test_the_patch_keeps_every_metered_line_and_day(self):
		lines, days = self.lines(), self.days()
		unfold()
		self.assertEqual(self.lines(), lines, "the day ledger bills the same lines")
		self.assertEqual(self.days(), [])

		fold_usage_days_into_months.execute()

		self.assertEqual(self.lines(), lines)
		self.assertEqual(self.days(), days)
		self.assertFalse(usage_fold.ledger_rollups())
		self.assertTrue(frappe.db.count("Usage Day"), "the old days stay, read only")

	def test_a_billed_month_bills_nothing_again_after_the_patch(self):
		unfold()
		fold_usage_days_into_months.execute()
		for team, invoice in self.invoices.items():
			self.assertEqual(usage_recount.recount_team(team, JUNE[1]).months, [])
			billed = [
				day.invoice for day in usage_days(team=team, month=JUNE[0]) if day.dimension == "gpt-4o"
			]
			self.assertEqual(set(billed), {invoice})
		with feed(rate_on("2026-07-01", 85.0)):
			july = self.invoice_lines(TEAM_INR, JULY)
		# Claude nets -0.5 in June and +1.0 in July: only July and that carry are billed.
		self.assertEqual(
			[(line.description.split(" · ")[0], line.amount) for line in july],
			[("gpt-4o", 85.0), ("claude-sonnet", 42.5)],
		)

	def test_each_folded_day_names_a_migrated_report(self):
		unfold()
		fold_usage_days_into_months.execute()
		reports = {day.report for day in usage_days(team=TEAM_INR)}
		self.assertEqual(
			{frappe.db.get_value("Usage Report", name, "kind") for name in reports}, {"Migrated"}
		)

	def test_a_day_an_older_worker_writes_after_the_patch_is_folded_on_the_next_recount(self):
		unfold()
		fold_usage_days_into_months.execute()
		day = frappe.get_doc(
			{
				"doctype": "Usage Day",
				**{
					name: value
					for name, value in usage_days(team=TEAM_USD)[-1].items()
					if name in _DAY_FIELDS
				},
				"day": datetime.date(2026, 7, 7),
				"quantity": 2.0,
				"invoice": None,
			}
		)
		day.db_insert()
		usage_fold.fold_stragglers()
		self.assertIn(
			(datetime.date(2026, 7, 7), 2.0), [(d.day, d.quantity) for d in usage_days(team=TEAM_USD)]
		)


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
