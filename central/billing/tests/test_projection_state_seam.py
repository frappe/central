# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The evolving-state seam.

A decision function can be free of writes and still be un-projectable, because it
reads *now*. These readers take an optional source so a projection can answer them
from its own roll-forward; every production caller leaves it out and gets the
database, unchanged.
"""

import frappe
from central.billing.payments import settlement
from central.billing.revenue import credits
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import ensure_team, set_team_tier

TEAM = "team-state-seam"


class FakeState:
	"""Stands in for a projection's roll-forward."""

	def __init__(self, balance=0.0, has_autopay=False, tier_cap=0.0):
		self._balance = balance
		self._autopay = has_autopay
		self._cap = tier_cap
		self.asked = []

	def balance(self, team, currency):
		self.asked.append(("balance", team, currency))
		return self._balance

	def has_autopay(self, team):
		return self._autopay

	def tier_cap(self, team):
		return self._cap


class SeamTestBase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		self._purge()
		set_team_tier(TEAM, level="t0", max_spend=5000)
		frappe.db.commit()

	def tearDown(self):
		self._purge()

	def _purge(self):
		frappe.db.delete("Credit Ledger Entry", {"team": TEAM})
		frappe.db.delete("Credit Wallet", {"team": TEAM})
		frappe.db.delete("Payment Method", {"team": TEAM})
		frappe.db.delete("Billing Profile", {"team": TEAM})
		frappe.db.commit()


class TestProductionBehaviourIsUnchanged(SeamTestBase):
	def test_the_balance_still_comes_off_the_wallet_anchor(self):
		credits.purchase(TEAM, 700, "INR")
		frappe.db.commit()
		self.assertEqual(credits.get_balance(TEAM)["balance"], 700.0)

	def test_the_cap_still_comes_off_the_tier(self):
		self.assertEqual(settlement.effective_spend_cap(TEAM), 5000.0)

	def test_settlement_sources_still_read_live(self):
		credits.purchase(TEAM, 10, "INR")
		frappe.db.commit()
		sources = settlement.settlement_sources(TEAM)
		self.assertTrue(sources["has_credits"])
		self.assertTrue(sources["credits_only"])


class TestASourceIsConsultedInstead(SeamTestBase):
	def test_the_wallet_is_answered_by_the_projection(self):
		credits.purchase(TEAM, 700, "INR")
		frappe.db.commit()
		state = FakeState(balance=42.0)
		self.assertEqual(credits.get_balance(TEAM, source=state)["balance"], 42.0)
		self.assertTrue(state.asked)

	def test_the_currency_is_still_resolved_from_the_profile(self):
		# Currency is reference data, not evolving state — it keeps coming off the profile.
		credits.purchase(TEAM, 1, "INR")
		frappe.db.commit()
		self.assertEqual(credits.get_balance(TEAM, source=FakeState())["currency"], "INR")

	def test_a_projected_wallet_drives_the_credits_only_cap(self):
		# The whole point: month four must draw against what the projection has left,
		# not against the balance the team happens to hold today.
		credits.purchase(TEAM, 5000, "INR")
		frappe.db.commit()
		state = FakeState(balance=120.0, has_autopay=False, tier_cap=5000.0)
		self.assertEqual(settlement.effective_spend_cap(TEAM, source=state), 120.0)

	def test_an_autopay_team_follows_the_projected_tier_cap(self):
		state = FakeState(balance=0.0, has_autopay=True, tier_cap=9000.0)
		self.assertEqual(settlement.effective_spend_cap(TEAM, source=state), 9000.0)

	def test_spend_acceptance_uses_the_projected_state(self):
		state = FakeState(balance=100.0, has_autopay=False, tier_cap=5000.0)
		self.assertTrue(settlement.can_accept_spend(TEAM, 90, source=state))
		self.assertFalse(settlement.can_accept_spend(TEAM, 110, source=state))

	def test_the_forecast_compares_against_the_projected_wallet(self):
		out = settlement.credit_forecast(TEAM, 90, notify=False, source=FakeState(balance=100.0))
		self.assertEqual(out["balance"], 100.0)
		self.assertEqual(out["shortfall"], 0.0)


class TestReferenceDataIsNotVirtualised(SeamTestBase):
	def test_tax_resolution_takes_no_source(self):
		# Projecting forward does not change a team's tax profile, so it keeps reading
		# live. Only what the projection itself changes needs the seam.
		import inspect

		from central.billing.revenue.tax import resolve_tax

		self.assertNotIn("source", inspect.signature(resolve_tax).parameters)

	def test_commitment_resolution_takes_no_source(self):
		import inspect

		from central.billing.catalog.commitments import resolve_commitment

		self.assertNotIn("source", inspect.signature(resolve_commitment).parameters)
