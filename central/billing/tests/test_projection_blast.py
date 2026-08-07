# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Blast radius: how far a change reaches across the book.

The metric set is provisional by design — the issue is HITL because which numbers
matter is a conversation with the accounts team. What these tests hold is the shape:
counted from two projections, never modelled; money never crossed between currencies;
and an extrapolated figure that says so.
"""

from central.billing.projection import blast
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase


def row(team, total=1000.0, currency="INR", shortfall=0.0, suspends_on=None):
	return {
		"team": team,
		"currency": currency,
		"projected_total": total,
		"shortfall": shortfall,
		"suspends_on": suspends_on,
	}


class TestTheComparison(IntegrationTestCase):
	def test_revenue_moves_are_counted_per_currency(self):
		out = blast.compare_rows(
			[row("a", 1000, "INR"), row("b", 100, "USD")],
			[row("a", 1200, "INR"), row("b", 150, "USD")],
		)
		self.assertEqual(out["revenue_delta"], {"INR": 200.0, "USD": 50.0})

	def test_currencies_are_never_summed_together(self):
		out = blast.compare_rows([row("a", 1000, "INR")], [row("a", 1200, "INR")])
		self.assertNotIn("total", out["revenue_delta"])
		self.assertEqual(list(out["revenue_delta"]), ["INR"])

	def test_a_team_that_becomes_short_is_counted_once(self):
		out = blast.compare_rows(
			[row("a", shortfall=0)], [row("a", shortfall=500)]
		)
		self.assertEqual(out["newly_short"], ["a"])

	def test_a_team_already_short_is_not_counted_as_newly_short(self):
		out = blast.compare_rows(
			[row("a", shortfall=200)], [row("a", shortfall=500)]
		)
		self.assertEqual(out["newly_short"], [])

	def test_a_suspension_appearing_is_distinguished_from_one_moving(self):
		# Whether these are the same finding is exactly the judgement the accounts team
		# has to make, so they are counted apart rather than merged.
		out = blast.compare_rows(
			[row("a"), row("b", suspends_on="2026-10-22")],
			[row("a", suspends_on="2026-10-20"), row("b", suspends_on="2026-10-15")],
		)
		self.assertEqual(out["newly_suspending"], ["a"])
		self.assertEqual(out["suspension_moved_earlier"], ["b"])

	def test_a_suspension_moving_later_is_counted_separately_again(self):
		out = blast.compare_rows(
			[row("a", suspends_on="2026-10-10")], [row("a", suspends_on="2026-10-25")]
		)
		self.assertEqual(out["suspension_moved_later"], ["a"])
		self.assertEqual(out["suspension_moved_earlier"], [])

	def test_only_teams_present_on_both_sides_are_compared(self):
		out = blast.compare_rows([row("a"), row("b")], [row("a")])
		self.assertEqual(out["teams"], 1)

	def test_the_metrics_announce_themselves_as_provisional(self):
		out = blast.compare_rows([row("a")], [row("a")])
		self.assertTrue(out["provisional_metrics"])


class TestSummarising(IntegrationTestCase):
	def _comparison(self):
		return blast.compare_rows(
			[row("a", 1000), row("b", 1000, shortfall=0)],
			[row("a", 1200, suspends_on="2026-10-20"), row("b", 1000, shortfall=300)],
		)

	def test_counts_replace_the_lists(self):
		out = blast.summarise(self._comparison())
		self.assertEqual(out["newly_suspending"], 1)
		self.assertEqual(out["newly_short"], 1)

	def test_a_sampled_summary_says_so_and_carries_its_size(self):
		out = blast.summarise(self._comparison(), sampled=True, sample_size=2, population=200)
		self.assertTrue(out["sampled"])
		self.assertEqual(out["sample_size"], 2)
		self.assertIn("Extrapolated", out["note"])

	def test_money_is_extrapolated_but_team_counts_are_not(self):
		# Scaling "1 team newly suspending" to a population invents teams, and somebody
		# will go looking for them.
		out = blast.summarise(self._comparison(), sampled=True, sample_size=2, population=200)
		self.assertEqual(out["revenue_delta"]["INR"], 200.0)
		self.assertEqual(out["revenue_delta_extrapolated"]["INR"], 20000.0)
		self.assertEqual(out["newly_suspending"], 1)

	def test_an_unsampled_summary_offers_no_extrapolation_to_misread(self):
		out = blast.summarise(self._comparison())
		self.assertNotIn("revenue_delta_extrapolated", out)


class TestDescribing(IntegrationTestCase):
	def test_a_change_that_does_nothing_says_so_plainly(self):
		summary = blast.summarise(blast.compare_rows([row("a")], [row("a")]))
		self.assertIn("nothing measurable changes", blast.describe(summary))

	def test_a_change_that_bites_leads_with_the_damage(self):
		summary = blast.summarise(
			blast.compare_rows(
				[row("a", 1000)], [row("a", 1000, shortfall=500, suspends_on="2026-10-20")]
			)
		)
		line = blast.describe(summary)
		self.assertIn("newly suspending", line)
		self.assertIn("newly short", line)
