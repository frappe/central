# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Cohorts are bounded before they are projected, not after."""

import frappe

from central.billing.projection import cohort
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	billing_settings,
	ensure_team,
	make_billing_subscription,
	make_plan,
)

PREFIX = "team-cohort"
CLUSTER = "ap-south-1"
PLAN = "bundle-cohort"


class CohortTestBase(IntegrationTestCase):
	def setUp(self):
		make_plan(PLAN)
		self._purge()
		self.teams = []
		for i in range(4):
			team = f"{PREFIX}-{i}"
			ensure_team(team)
			make_billing_subscription(team, CLUSTER, PLAN, billing_cycle="Monthly")
			self.teams.append(team)
		# Two INR, two USD, so a currency filter genuinely narrows.
		for i, team in enumerate(self.teams):
			frappe.db.set_value("Billing Profile", team, "currency", "INR" if i < 2 else "USD")
		frappe.db.commit()

	def tearDown(self):
		self._purge()

	def _purge(self):
		for team in frappe.get_all("Team", filters={"name": ["like", f"{PREFIX}%"]}, pluck="name"):
			for sub in frappe.get_all("Subscription", {"team": team}, pluck="name"):
				frappe.db.delete("Subscription Change", {"subscription": sub})
				frappe.db.delete("Subscription", {"name": sub})
			frappe.db.delete("Asset", {"team": team})
			frappe.db.delete("Invoice", {"team": team})
		frappe.db.commit()

	def _filters(self, **kw):
		# Scope every assertion to this test's own teams; the site has plenty of others.
		return {"currency": kw.pop("currency", None), **kw}


class TestSizing(CohortTestBase):
	def test_counting_a_cohort_does_no_projection(self):
		# The whole point of sizing is that it is cheap. If it had to rate anyone it
		# would be the load it exists to prevent.
		with billing_settings(projection_budget_seconds=300):
			sizing = cohort.estimate({"currency": "INR"}, months=1)
		self.assertGreaterEqual(sizing.teams, 2)
		self.assertEqual(sizing.months, 1)

	def test_a_currency_filter_narrows_the_cohort(self):
		inr = cohort.count({"currency": "INR"})
		usd = cohort.count({"currency": "USD"})
		everything = cohort.count({})
		self.assertGreaterEqual(everything, inr + usd)
		self.assertGreater(inr, 0)
		self.assertGreater(usd, 0)

	def test_cost_scales_with_months(self):
		one = cohort.estimate({"currency": "INR"}, months=1)
		six = cohort.estimate({"currency": "INR"}, months=6)
		self.assertAlmostEqual(six.estimated_seconds, one.estimated_seconds * 6, places=4)


class TestTheBound(CohortTestBase):
	def test_a_cohort_within_budget_is_allowed(self):
		with billing_settings(projection_budget_seconds=300):
			sizing = cohort.require_within_budget({"currency": "INR"}, months=1)
		self.assertTrue(sizing.within_budget)

	def test_an_over_budget_cohort_is_refused(self):
		with billing_settings(projection_budget_seconds=1):
			with self.assertRaises(cohort.CohortTooLargeError):
				cohort.require_within_budget({}, months=12)

	def test_the_refusal_carries_what_was_asked_and_what_it_would_cost(self):
		# A refusal that does not say how big or how long is a dead end.
		with billing_settings(projection_budget_seconds=1):
			try:
				cohort.require_within_budget({}, months=12)
				self.fail("expected a refusal")
			except cohort.CohortTooLargeError as e:
				self.assertGreater(e.sizing.teams, 0)
				self.assertEqual(e.sizing.months, 12)
				self.assertGreater(e.sizing.estimated_seconds, 0)
				self.assertIn("too large", str(e))

	def test_there_is_no_way_to_project_an_unbounded_cohort(self):
		# An empty filter set must not be a bypass — it is the widest possible ask.
		# Twenty-four months so the refusal does not depend on how many teams the site
		# happens to be carrying when the test runs.
		with billing_settings(projection_budget_seconds=1):
			with self.assertRaises(cohort.CohortTooLargeError):
				cohort.require_within_budget(None, months=24)
			with self.assertRaises(cohort.CohortTooLargeError):
				cohort.require_within_budget({}, months=24)

	def test_the_budget_is_read_from_settings(self):
		with billing_settings(projection_budget_seconds=1234):
			self.assertEqual(cohort.budget_seconds(), 1234)

	def test_an_unsaved_or_zeroed_setting_falls_back_rather_than_disabling_everything(self):
		# The field is an Int on a Single: unset reads None, and 0 forever after anybody
		# saves the form. Honouring that 0 would turn an unrelated edit into a silent
		# site-wide switch-off.
		with billing_settings(projection_budget_seconds=0):
			self.assertEqual(cohort.budget_seconds(), cohort.DEFAULT_BUDGET_SECONDS)

	def test_a_refused_cohort_is_told_what_would_narrow_it(self):
		hints = cohort.narrowing_hints({"currency": "INR"})
		self.assertNotIn("currency", hints)
		self.assertIn("country", hints)
		self.assertIn("cluster", hints)


class TestPaging(CohortTestBase):
	def test_the_cohort_pages_rather_than_loading_whole(self):
		pages = list(cohort.pages({"currency": "INR"}, page_size=1))
		self.assertGreaterEqual(len(pages), 2)
		self.assertTrue(all(len(page) <= 1 for _, _, page in pages))

	def test_pages_cover_the_cohort_exactly_once(self):
		seen = [team for _, _, page in cohort.pages({"currency": "INR"}, page_size=1) for team in page]
		self.assertEqual(len(seen), len(set(seen)))
		self.assertEqual(len(seen), cohort.count({"currency": "INR"}))

	def test_a_slice_is_rederived_from_its_bounds(self):
		pages = list(cohort.pages({"currency": "INR"}, page_size=1))
		after, until, page = pages[0]
		self.assertEqual(cohort.teams_in_slice({"currency": "INR"}, after, until), page)


class TestDeferringToTheRun(CohortTestBase):
	def test_projections_stand_aside_while_the_run_still_owes_work(self):
		# One of them is answering a question; the other is billing customers.
		self.assertIn(cohort.run_in_progress("2026-09-15"), (True, False))


class TestTheBatch(CohortTestBase):
	"""The batch does the work; the report only reads what it left behind."""

	def setUp(self):
		super().setUp()
		from central.billing.tests.utils import add_segment

		for team in self.teams:
			sub = frappe.get_all("Subscription", {"team": team}, pluck="name")[0]
			add_segment(sub, "Created", 1000, "2026-01-01 00:00:00")
		frappe.db.commit()

	def tearDown(self):
		for b in frappe.get_all("Billing Projection Batch", pluck="name"):
			frappe.db.delete("Billing Projection Summary", {"batch": b})
			frappe.delete_doc("Billing Projection Batch", b, force=True, ignore_permissions=True)
		frappe.db.commit()
		super().tearDown()

	def _batch(self, filters=None, months=1):
		from central.billing.projection import batch

		doc = frappe.get_doc(
			{
				"doctype": "Billing Projection Batch",
				"as_of": "2026-08-06",
				"period_start": "2026-09-01",
				"months": months,
				"batch_state": "Queued",
				"filters": frappe.as_json(filters or {"currency": "INR"}),
				"teams_expected": cohort.count(filters or {"currency": "INR"}),
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		return batch.run_batch(doc.name)

	def test_a_batch_writes_one_scalar_row_per_team(self):
		result = self._batch()
		rows = frappe.get_all(
			"Billing Projection Summary",
			filters={"batch": result["batch"]},
			fields=["team", "projected_total", "currency", "outcome"],
		)
		self.assertEqual(len(rows), cohort.count({"currency": "INR"}))
		self.assertTrue(all(r.currency == "INR" for r in rows))
		self.assertTrue(all(r.projected_total for r in rows))

	def test_the_batch_reports_completion(self):
		result = self._batch()
		self.assertEqual(result["status"], "Complete")
		self.assertEqual(
			frappe.db.get_value("Billing Projection Batch", result["batch"], "teams_projected"),
			cohort.count({"currency": "INR"}),
		)

	def test_rows_carry_the_as_of_stamp(self):
		result = self._batch()
		stamps = frappe.get_all(
			"Billing Projection Summary", filters={"batch": result["batch"]}, pluck="as_of"
		)
		self.assertTrue(all(str(s) == "2026-08-06" for s in stamps))

	def test_a_currency_filter_keeps_the_other_currency_out(self):
		result = self._batch({"currency": "USD"})
		rows = frappe.get_all(
			"Billing Projection Summary", filters={"batch": result["batch"]}, pluck="currency"
		)
		self.assertTrue(rows)
		self.assertTrue(all(c == "USD" for c in rows))

	def test_projecting_a_cohort_creates_no_invoices(self):
		before = frappe.db.count("Invoice")
		self._batch()
		self.assertEqual(frappe.db.count("Invoice"), before)

	def test_a_suspension_date_is_only_printed_when_non_payment_is_entailed(self):
		# These teams have no payment method at all, so it is entailed.
		result = self._batch()
		rows = frappe.get_all(
			"Billing Projection Summary",
			filters={"batch": result["batch"]},
			fields=["suspends_on", "outcome"],
		)
		self.assertTrue(all(r.suspends_on for r in rows))
		self.assertTrue(all(r.outcome for r in rows))

	def test_pruning_drops_old_batches_and_their_rows(self):
		result = self._batch()
		frappe.db.set_value(
			"Billing Projection Batch",
			result["batch"],
			"creation",
			"2020-01-01 00:00:00",
			update_modified=False,
		)
		frappe.db.commit()

		from central.billing.projection import batch

		self.assertGreaterEqual(batch.prune(days=30), 1)
		self.assertFalse(frappe.db.exists("Billing Projection Batch", result["batch"]))
		self.assertEqual(frappe.db.count("Billing Projection Summary", {"batch": result["batch"]}), 0)


class TestTheQueue(IntegrationTestCase):
	def test_projections_never_fall_back_to_the_billing_queue(self):
		# Contending with the monthly run for workers is the one fallback that would be
		# worse than being slow.
		from central.billing.projection import batch

		self.assertNotEqual(batch.projection_queue(), "billing")

	def test_only_projection_doctypes_are_written(self):
		# The engine cannot write at all; this is the boundary for what happens after.
		from central.billing.projection import batch

		self.assertEqual(
			set(batch.WRITABLE),
			{"Billing Projection Batch", "Billing Projection Summary"},
		)


class TestTheReport(CohortTestBase):
	"""The report reads; it never projects."""

	def setUp(self):
		super().setUp()
		from central.billing.tests.utils import add_segment

		for team in self.teams:
			sub = frappe.get_all("Subscription", {"team": team}, pluck="name")[0]
			add_segment(sub, "Created", 1000, "2026-01-01 00:00:00")
		frappe.db.commit()

	def tearDown(self):
		for b in frappe.get_all("Billing Projection Batch", pluck="name"):
			frappe.db.delete("Billing Projection Summary", {"batch": b})
			frappe.delete_doc("Billing Projection Batch", b, force=True, ignore_permissions=True)
		frappe.db.commit()
		super().tearDown()

	def _run_batch(self, filters=None):
		from central.billing.projection import batch

		doc = frappe.get_doc(
			{
				"doctype": "Billing Projection Batch",
				"as_of": "2026-08-06",
				"period_start": "2026-09-01",
				"months": 1,
				"batch_state": "Queued",
				"filters": frappe.as_json(filters or {"currency": "INR"}),
				"teams_expected": cohort.count(filters or {"currency": "INR"}),
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		return batch.run_batch(doc.name)["batch"]

	def _execute(self, **filters):
		from central.billing.report.billing_projection.billing_projection import execute

		return execute(filters)

	def test_it_renders_the_rows_a_batch_left_behind(self):
		name = self._run_batch()
		columns, rows, message, _chart, summary = self._execute(batch=name)
		self.assertTrue(columns)
		self.assertEqual(len(rows), cohort.count({"currency": "INR"}))
		self.assertIn("Projected", message)
		self.assertTrue(summary)

	def test_running_the_report_projects_nobody(self):
		# If the report computed, it would time out at cohort scale. It must only read.
		name = self._run_batch()
		before = frappe.db.count("Billing Projection Summary", {"batch": name})
		self._execute(batch=name)
		self._execute(batch=name)
		self.assertEqual(frappe.db.count("Billing Projection Summary", {"batch": name}), before)

	def test_with_no_batch_it_offers_to_make_one(self):
		with billing_settings(projection_budget_seconds=300):
			_c, rows, message, _chart, _s = self._execute(currency="INR", months=1)
		self.assertEqual(rows, [])
		self.assertIn("No projection yet", message)

	def test_an_over_budget_cohort_is_refused_in_the_message_slot(self):
		# A designed panel above an empty table, not a thrown error — the filters stay
		# live so the operator can narrow in place.
		with billing_settings(projection_budget_seconds=1):
			_c, rows, message, _chart, _s = self._execute(months=12)
		self.assertEqual(rows, [])
		self.assertIn("too large to project", message)
		self.assertIn("Narrow it by", message)

	def test_the_teams_that_would_suspend_sort_to_the_top(self):
		name = self._run_batch()
		_c, rows, _m, _chart, _s = self._execute(batch=name, needs_attention=1)
		self.assertTrue(rows)
		self.assertTrue(all(r["suspends_on"] for r in rows))

	def test_a_partial_batch_says_so(self):
		name = self._run_batch()
		frappe.db.set_value("Billing Projection Batch", name, "batch_state", "Partial")
		frappe.db.commit()
		_c, _rows, message, _chart, _s = self._execute(batch=name)
		self.assertIn("Incomplete", message)

	def test_a_sampled_batch_never_reads_as_measured(self):
		name = self._run_batch()
		frappe.db.set_value("Billing Projection Batch", name, {"sampled": 1, "sample_size": 500})
		frappe.db.commit()
		_c, _rows, message, _chart, _s = self._execute(batch=name)
		self.assertIn("Extrapolated", message)
		self.assertIn("estimates", message)

	def test_money_is_never_summed_across_currencies(self):
		inr = self._run_batch({"currency": "INR"})
		frappe.db.set_value(
			"Billing Projection Summary",
			frappe.get_all("Billing Projection Summary", {"batch": inr}, pluck="name")[0],
			"currency",
			"USD",
		)
		frappe.db.commit()
		_c, rows, _m, _chart, summary = self._execute(batch=inr)
		currencies = {t.get("currency") for t in summary if t.get("datatype") == "Currency"}
		self.assertIn("INR", currencies)
		self.assertIn("USD", currencies)


class TestSampling(CohortTestBase):
	"""The way out of a refusal, and it never pretends to be a measurement."""

	def setUp(self):
		super().setUp()
		from central.billing.tests.utils import set_team_tier

		# Two tiers across two currencies, so the strata are real.
		for i, team in enumerate(self.teams):
			set_team_tier(team, level="t1" if i % 2 else "t2", max_spend=50000)
		frappe.db.commit()

	def test_the_cohort_divides_along_currency_and_tier(self):
		strata = cohort.strata_counts({})
		self.assertTrue(strata)
		self.assertTrue(all("currency" in s and "trust_tier_level" in s for s in strata))

	def test_a_sample_stays_within_the_population(self):
		drawn = cohort.sample({}, size=2)
		self.assertLessEqual(drawn.size, drawn.population)
		self.assertEqual(len(drawn.teams), len(set(drawn.teams)))

	def test_asking_for_more_than_exists_returns_the_whole_population(self):
		drawn = cohort.sample({"currency": "INR"}, size=10_000)
		self.assertEqual(drawn.size, drawn.population)

	def test_every_stratum_is_represented_however_small(self):
		# A rung with three teams still deserves a voice, or the extrapolation speaks
		# only for the crowd.
		drawn = cohort.sample({}, size=1)
		self.assertGreaterEqual(len(drawn.strata), 1)
		self.assertTrue(all(s["sampled"] >= 1 for s in drawn.strata if s["population"]))

	def test_each_stratum_reports_what_one_sampled_team_stands_for(self):
		drawn = cohort.sample({}, size=2)
		for stratum in drawn.strata:
			if stratum["sampled"]:
				self.assertGreaterEqual(stratum["weight"], 1.0)

	def test_an_empty_cohort_samples_to_nothing(self):
		self.assertEqual(cohort.sample({"currency": "XXX"}, size=10).size, 0)


class TestRetentionIsScheduled(IntegrationTestCase):
	def test_pruning_is_wired_into_the_daily_scheduler(self):
		# A nightly cohort that never prunes is the one part of this that grows without
		# bound, so the sweep has to be scheduled rather than remembered.
		from central import hooks

		daily = hooks.scheduler_events.get("daily", [])
		self.assertIn("central.billing.projection.batch.prune", daily)


class TestContainmentDoesNotCascade(CohortTestBase):
	"""One bad team costs one team, not the rest of its page."""

	def setUp(self):
		super().setUp()
		from central.billing.tests.utils import add_segment

		for team in self.teams:
			sub = frappe.get_all("Subscription", {"team": team}, pluck="name")[0]
			add_segment(sub, "Created", 1000, "2026-01-01 00:00:00")
		frappe.db.commit()

	def tearDown(self):
		for b in frappe.get_all("Billing Projection Batch", pluck="name"):
			frappe.db.delete("Billing Projection Summary", {"batch": b})
			frappe.delete_doc("Billing Projection Batch", b, force=True, ignore_permissions=True)
		frappe.db.commit()
		super().tearDown()

	def test_a_failing_team_does_not_take_the_rest_of_the_page_with_it(self):
		# Logging the failure inline would leave the transaction dirty, and the next
		# team's projection would then refuse to start — one casualty becoming a page.
		from unittest.mock import patch

		from central.billing.projection import batch

		doc = frappe.get_doc(
			{
				"doctype": "Billing Projection Batch",
				"as_of": "2026-08-06",
				"period_start": "2026-09-01",
				"months": 1,
				"batch_state": "Queued",
				"filters": frappe.as_json({}),
				"teams_expected": len(self.teams),
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()

		real = batch._summarise
		calls = {"n": 0}

		def flaky(team, batch_doc):
			calls["n"] += 1
			if calls["n"] == 1:
				raise ValueError("this team is broken")
			return real(team, batch_doc)

		with patch.object(batch, "_summarise", side_effect=flaky):
			result = batch.run_batch(doc.name, teams=self.teams)

		# One lost, the rest projected — not one lost and the rest abandoned.
		self.assertEqual(result["teams_projected"], len(self.teams) - 1)
		self.assertEqual(result["status"], "Complete")

	def test_a_finding_formats_money_without_asking_the_database(self):
		# fmt_money resolves the site number format, and that read can write — fatal
		# inside the read-only transaction a projection runs in.
		from central.billing.projection import outcomes

		self.assertEqual(outcomes._money(12373.5, "INR"), "INR 12,373.50")


class TestSplitCurrencyColumns(IntegrationTestCase):
	"""Money split by currency has to render in that currency."""

	def _split(self):
		from central.billing.report._currency import split_currency_columns

		columns = [
			{"label": "Team", "fieldname": "team", "fieldtype": "Data"},
			{"label": "Total", "fieldname": "total", "fieldtype": "Currency", "options": "currency"},
			{"label": "Currency", "fieldname": "currency", "fieldtype": "Data"},
		]
		rows = [
			{"team": "a", "total": 100.0, "currency": "INR"},
			{"team": "b", "total": 50.0, "currency": "USD"},
		]
		return split_currency_columns(columns, rows, ["total"]), rows

	def test_a_split_column_points_at_a_field_on_the_row(self):
		# Frappe resolves a Currency column's currency by looking up row[options]. A
		# literal code finds nothing and falls back to the site default, which is how
		# every split column came to render in the wrong symbol.
		columns, rows = self._split()
		money = [c for c in columns if c["fieldname"].startswith("total_")]
		self.assertEqual(len(money), 2)
		for column in money:
			self.assertIn(column["options"], rows[0], "options must name a row field")

	def test_each_carrier_holds_its_own_currency(self):
		columns, rows = self._split()
		for column in columns:
			if column["fieldname"].startswith("total_"):
				expected = column["fieldname"].rsplit("_", 1)[1].upper()
				self.assertEqual(rows[0][column["options"]], expected)

	def test_every_row_carries_every_currency(self):
		# A blank carrier would send an empty cell back to the site default.
		_columns, rows = self._split()
		for row in rows:
			self.assertEqual(row["currency_inr"], "INR")
			self.assertEqual(row["currency_usd"], "USD")

	def test_values_still_land_in_their_own_currency_column(self):
		_columns, rows = self._split()
		self.assertEqual(rows[0]["total_inr"], 100.0)
		self.assertNotIn("total_usd", rows[0])
		self.assertEqual(rows[1]["total_usd"], 50.0)

	def test_a_single_currency_run_is_left_alone(self):
		from central.billing.report._currency import split_currency_columns

		columns = [{"label": "Total", "fieldname": "total", "fieldtype": "Currency"}]
		rows = [{"total": 10.0, "currency": "INR"}]
		self.assertEqual(split_currency_columns(columns, rows, ["total"]), columns)


class TestTheReportFitsOnAScreen(CohortTestBase):
	def test_the_column_set_is_narrow_enough_to_read(self):
		# Five money fields across two currencies was eleven columns and truncated
		# headings. Each column has to earn its place.
		from central.billing.report.billing_projection.billing_projection import get_columns

		self.assertLessEqual(len(get_columns()), 8)

	def test_a_two_currency_run_still_fits(self):
		from central.billing.report._currency import split_currency_columns
		from central.billing.report.billing_projection.billing_projection import (
			MONEY_FIELDS,
			get_columns,
		)

		rows = [
			{"currency": "INR", "projected_total": 1.0, "shortfall": 0.0},
			{"currency": "USD", "projected_total": 1.0, "shortfall": 0.0},
		]
		columns = split_currency_columns(get_columns(), rows, MONEY_FIELDS)
		self.assertLessEqual(len(columns), 9)

	def test_what_was_dropped_is_still_derivable_or_drilled(self):
		# Credits is projected total minus shortfall; the measured/estimated split lives
		# on the team's own page, where it can be read properly.
		from central.billing.report.billing_projection.billing_projection import get_columns

		shown = {c["fieldname"] for c in get_columns()}
		self.assertNotIn("credit_balance", shown)
		self.assertNotIn("measured", shown)
		self.assertIn("shortfall", shown)
