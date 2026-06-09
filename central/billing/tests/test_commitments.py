# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Commitment — team spend-floor + discounted monthly invoice (issue #30).

A Commitment is a team-level promise to keep monthly FIXED-BUNDLE spend at or
above a floor for a term, in exchange for a discount on each monthly-in-arrears
invoice. The discount + floor are measured on fixed-bundle spend only; metered
usage and one-off add-ons bill at list. See final-plan-pricing.md §5 / ADR 0001.
"""

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.revenue import invoicing
from central.billing.catalog import subscriptions
from central.billing.platform.sync import receive_usage_events
from central.billing.tests.utils import make_plan

TEAM = "team-commitment"
CLUSTER = "ap-south-1"
PLAN = "bundle-commitment-test"


def push_event(event_id, resource_id, rate, effective_from, event_type="subscribed", team=TEAM):
	receive_usage_events(
		[
			{
				"event_id": event_id,
				"team": team,
				"resource_id": resource_id,
				"cluster": CLUSTER,
				"plan": PLAN,
				"shown_rate": rate,
				"currency": "INR",
				"event_type": event_type,
				"effective_from": effective_from,
				"effective_to": None,
			}
		]
	)


def make_commitment(team, floor, discount_pct, started_at="2026-06-01", term_months=12, currency="INR"):
	frappe.db.delete("Commitment", {"team": team})
	return frappe.get_doc(
		{
			"doctype": "Commitment",
			"team": team,
			"floor": floor,
			"currency": currency,
			"discount_pct": discount_pct,
			"term_months": term_months,
			"started_at": started_at,
			"status": "Active",
		}
	).insert(ignore_permissions=True).name


class CommitmentTestBase(IntegrationTestCase):
	def setUp(self):
		make_plan(PLAN)
		self._purge()
		self.sub = subscriptions.create_subscription(
			team=TEAM, cluster=CLUSTER, plan=PLAN, billing_cycle="monthly"
		).name

	def tearDown(self):
		self._purge()

	def _purge(self):
		for dt in ("Invoice", "Price Lock", "Usage Rollup", "Commitment"):
			frappe.db.delete(dt, {"team": TEAM})
		for sub in frappe.get_all("Subscription", {"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": sub})
			frappe.db.delete("Subscription", {"name": sub})
		frappe.db.commit()


class TestCommitmentDiscount(CommitmentTestBase):
	def test_floor_met_applies_discount(self):
		# Bundle runs all of June at 1000/mo -> fixed-bundle spend = 1000.
		push_event("e1", "R1", 1000, "2026-06-01 00:00:00", "subscribed")
		make_commitment(TEAM, floor=800, discount_pct=20)

		name = invoicing.generate_draft_invoice(self.sub, "2026-06-01", "2026-06-30")
		inv = frappe.get_doc("Invoice", name)

		self.assertEqual(inv.subtotal, 1000.0)  # gross, unchanged
		self.assertEqual(inv.commitment_discount, 200.0)  # 20% of 1000, floor met
		self.assertEqual(inv.total, 800.0)  # taxable base discounted (no tax for this team)
		self.assertEqual(inv.expected_collection, 800.0)

	def test_floor_not_met_no_discount(self):
		# Bundle spend 500 (half a month) is below the 800 floor -> no discount.
		push_event("e1", "R1", 1000, "2026-06-16 00:00:00", "subscribed")  # Jun16-30 = 15d
		make_commitment(TEAM, floor=800, discount_pct=20)

		name = invoicing.generate_draft_invoice(self.sub, "2026-06-01", "2026-06-30")
		inv = frappe.get_doc("Invoice", name)

		self.assertEqual(inv.subtotal, 500.0)  # 15 * 1000/30
		self.assertEqual(inv.commitment_discount, 0.0)
		self.assertEqual(inv.total, 500.0)

	def _metered_rollup(self, resource_id, resource_type, quantity, rate):
		frappe.get_doc(
			{
				"doctype": "Usage Rollup",
				"resource_id": resource_id,
				"team": TEAM,
				"cluster": CLUSTER,
				"resource_type": resource_type,
				"meter_type": "counter",
				"period_start": "2026-06-01",
				"period_end": "2026-06-30",
				"quantity": quantity,
				"unit": "GB",
				"currency": "INR",
				"locked_allowance": 0,
				"locked_rate": rate,
				"idempotency_key": f"{resource_id}-2026-06",
			}
		).insert(ignore_permissions=True)

	def test_discount_base_is_fixed_bundle_only(self):
		# Bundle 1000 (discountable) + metered transfer 300 (billed at list).
		push_event("e1", "R1", 1000, "2026-06-01 00:00:00", "subscribed")
		self._metered_rollup("R-transfer", "transfer", quantity=300, rate=1)
		make_commitment(TEAM, floor=800, discount_pct=20)

		name = invoicing.generate_draft_invoice(self.sub, "2026-06-01", "2026-06-30")
		inv = frappe.get_doc("Invoice", name)

		self.assertEqual(inv.subtotal, 1300.0)  # 1000 bundle + 300 metered, gross
		self.assertEqual(inv.commitment_discount, 200.0)  # 20% of bundle 1000 only, not 1300
		self.assertEqual(inv.total, 1100.0)  # 1300 - 200

	def test_no_commitment_leaves_invoice_unchanged(self):
		push_event("e1", "R1", 1000, "2026-06-01 00:00:00", "subscribed")
		# No commitment created.
		name = invoicing.generate_draft_invoice(self.sub, "2026-06-01", "2026-06-30")
		inv = frappe.get_doc("Invoice", name)

		self.assertEqual(inv.commitment_discount, 0.0)
		self.assertEqual(inv.subtotal, 1000.0)
		self.assertEqual(inv.total, 1000.0)


class TestCommitmentClawback(CommitmentTestBase):
	def test_breach_below_floor_claws_back_discount_enjoyed(self):
		commitment = make_commitment(TEAM, floor=800, discount_pct=20, started_at="2026-06-01")

		# June: full month at 1000 -> floor met, discount 200 enjoyed.
		push_event("e1", "R1", 1000, "2026-06-01 00:00:00", "subscribed")
		june = invoicing.generate_draft_invoice(self.sub, "2026-06-01", "2026-06-30")
		self.assertEqual(frappe.get_doc("Invoice", june).commitment_discount, 200.0)

		# July: resource terminated Jul16 -> 15 days, spend < 800 floor -> breach.
		push_event("e2", "R1", 1000, "2026-07-16 00:00:00", "cancelled")
		july = invoicing.generate_draft_invoice(self.sub, "2026-07-01", "2026-07-31")
		inv = frappe.get_doc("Invoice", july)

		self.assertEqual(inv.commitment_discount, 0.0)  # no discount in the breach month
		self.assertEqual(inv.commitment_clawback, 200.0)  # repay June's discount
		self.assertEqual(inv.total, frappe.utils.flt(inv.subtotal + 200.0, 2))  # clawback added to base
		self.assertEqual(frappe.db.get_value("Commitment", commitment, "status"), "Breached")

	def test_upgrade_above_floor_does_not_breach(self):
		commitment = make_commitment(TEAM, floor=800, discount_pct=20, started_at="2026-06-01")

		# June at 1000, then July upgraded to 2000 — spend stays above the floor.
		push_event("e1", "R1", 1000, "2026-06-01 00:00:00", "subscribed")
		invoicing.generate_draft_invoice(self.sub, "2026-06-01", "2026-06-30")
		push_event("e2", "R1", 2000, "2026-07-01 00:00:00", "changed")
		july = invoicing.generate_draft_invoice(self.sub, "2026-07-01", "2026-07-31")
		inv = frappe.get_doc("Invoice", july)

		self.assertEqual(inv.commitment_clawback, 0.0)  # spending more never claws back
		self.assertEqual(inv.commitment_discount, 400.0)  # 20% of 2000, still discounted
		self.assertEqual(frappe.db.get_value("Commitment", commitment, "status"), "Active")

	def test_clawback_is_idempotent(self):
		commitment = make_commitment(TEAM, floor=800, discount_pct=20, started_at="2026-06-01")
		push_event("e1", "R1", 1000, "2026-06-01 00:00:00", "subscribed")
		invoicing.generate_draft_invoice(self.sub, "2026-06-01", "2026-06-30")
		push_event("e2", "R1", 1000, "2026-07-16 00:00:00", "cancelled")

		first = invoicing.generate_draft_invoice(self.sub, "2026-07-01", "2026-07-31")
		second = invoicing.generate_draft_invoice(self.sub, "2026-07-01", "2026-07-31")

		self.assertEqual(first, second)  # same invoice, not a second one
		self.assertEqual(frappe.get_doc("Invoice", second).commitment_clawback, 200.0)  # not doubled
		self.assertEqual(frappe.db.count("Invoice", {"team": TEAM, "period_start": "2026-07-01"}), 1)
