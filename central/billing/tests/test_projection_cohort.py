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
		for team in frappe.get_all(
			"Team", filters={"name": ["like", f"{PREFIX}%"]}, pluck="name"
		):
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
		with billing_settings(projection_budget_seconds=0):
			with self.assertRaises(cohort.CohortTooLargeError):
				cohort.require_within_budget({}, months=12)

	def test_the_refusal_carries_what_was_asked_and_what_it_would_cost(self):
		# A refusal that does not say how big or how long is a dead end.
		with billing_settings(projection_budget_seconds=0):
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
		with billing_settings(projection_budget_seconds=0):
			with self.assertRaises(cohort.CohortTooLargeError):
				cohort.require_within_budget(None, months=1)
			with self.assertRaises(cohort.CohortTooLargeError):
				cohort.require_within_budget({}, months=1)

	def test_the_budget_is_read_from_settings(self):
		with billing_settings(projection_budget_seconds=1234):
			self.assertEqual(cohort.budget_seconds(), 1234)

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
