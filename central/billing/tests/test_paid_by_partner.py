# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Paid-by-Partner billing redirection (ADR 0007, v2-billing-specs)."""

import frappe

from central.billing.revenue.invoicing import generate
from central.billing.tests.utils import BillingTestCase, add_segment, ensure_team, make_billing_subscription, make_plan

CLUSTER = "ap-south-1"
PLAN = "bundle-pbp-test"
PARTNER_TEAM = "pbp-partner-team"
CLIENT_TEAM_A = "pbp-client-a"  # whole period paid by partner
CLIENT_TEAM_B = "pbp-client-b"  # mid-period delink


def _link(partner_team, client_team, approved_on, delinked_on=None, status="Approved"):
	doc = frappe.get_doc(
		{
			"doctype": "Partner Client Link",
			"partner_team": partner_team,
			"client_team": client_team,
			"status": "Pending",
			"paid_by_partner": 1,
		}
	)
	doc.insert(ignore_permissions=True)
	# Back-date approval directly — .approve() would stamp "now", but these tests
	# need a specific historical approved_on to sit inside the billing period.
	doc.status = "Approved"
	doc.approved_on = approved_on
	doc.save(ignore_permissions=True)
	if delinked_on:
		doc.status = "Delinked"
		doc.delinked_on = delinked_on
		doc.save(ignore_permissions=True)
	elif status != "Approved":
		doc.status = status
		doc.save(ignore_permissions=True)
	return doc.name


class TestPaidByPartner(BillingTestCase):
	def setUp(self):
		make_plan(PLAN)
		ensure_team(PARTNER_TEAM)
		frappe.get_doc(
			{"doctype": "Partner Profile", "team": PARTNER_TEAM, "connect_partner": "TEST-PARTNER"}
		).insert(ignore_permissions=True)

		self.sub_a = make_billing_subscription(CLIENT_TEAM_A, CLUSTER, PLAN)
		add_segment(self.sub_a, "Created", 3000, "2026-06-01 00:00:00")

		self.sub_b = make_billing_subscription(CLIENT_TEAM_B, CLUSTER, PLAN)
		add_segment(self.sub_b, "Created", 3000, "2026-06-01 00:00:00")

	def test_whole_period_paid_by_partner(self):
		_link(PARTNER_TEAM, CLIENT_TEAM_A, approved_on="2026-05-15 00:00:00")

		client_rated = generate.rate_team_period(CLIENT_TEAM_A, "2026-06-01", "2026-06-30")
		self.assertIsNotNone(client_rated, "client invoice still generates (as a covered-by record)")
		client_items = client_rated.payload["items"]
		self.assertEqual(client_rated.payload["subtotal"], 0, "fully covered — nothing billed to the client")
		covered = [i for i in client_items if i.get("covered_by") == PARTNER_TEAM]
		self.assertEqual(len(covered), 1)
		self.assertEqual(covered[0]["amount"], 0)
		self.assertEqual(covered[0]["covered_amount"], 3000)

		partner_rated = generate.rate_team_period(PARTNER_TEAM, "2026-06-01", "2026-06-30")
		self.assertIsNotNone(partner_rated, "partner has no subscriptions of its own, but consolidates the client")
		partner_items = partner_rated.payload["items"]
		sourced = [i for i in partner_items if i.get("source_team") == CLIENT_TEAM_A]
		self.assertEqual(len(sourced), 1)
		self.assertEqual(sourced[0]["amount"], 3000)
		self.assertEqual(partner_rated.payload["subtotal"], 3000, "the partner is billed the client's full usage")

	def test_mid_period_delink_splits_by_day(self):
		# Approved from the start of June, delinked on the 15th — days 1-15 to the
		# partner, 16-30 to the client itself, per the user's explicit decision.
		_link(PARTNER_TEAM, CLIENT_TEAM_B, approved_on="2026-06-01 00:00:00", delinked_on="2026-06-15 00:00:00")

		client_rated = generate.rate_team_period(CLIENT_TEAM_B, "2026-06-01", "2026-06-30")
		client_items = client_rated.payload["items"]
		covered = [i for i in client_items if i.get("covered_by") == PARTNER_TEAM]
		own = [i for i in client_items if not i.get("covered_by")]
		self.assertEqual(len(covered), 1)
		self.assertEqual(covered[0]["amount"], 0)
		# 15 of 30 days at rate 3000 = 1500, exactly half the month.
		self.assertEqual(covered[0]["covered_amount"], 1500)
		self.assertEqual(sum(i["amount"] for i in own), 1500, "the other 15 days are billed to the client itself")
		self.assertEqual(client_rated.payload["subtotal"], 1500)

		partner_rated = generate.rate_team_period(PARTNER_TEAM, "2026-06-01", "2026-06-30")
		partner_items = partner_rated.payload["items"]
		sourced = [i for i in partner_items if i.get("source_team") == CLIENT_TEAM_B]
		self.assertEqual(len(sourced), 1)
		self.assertEqual(sourced[0]["amount"], 1500, "the partner is billed exactly the covered half")
		# The two sides of the same split must add back to the whole month's cost.
		self.assertEqual(covered[0]["covered_amount"] + sourced[0]["amount"], 3000)

	def test_unrelated_team_is_unaffected(self):
		"""No Partner Client Link at all — byte-for-byte the pre-ADR behaviour."""
		rated = generate.rate_team_period(CLIENT_TEAM_A, "2026-06-01", "2026-06-30")
		items = rated.payload["items"]
		self.assertTrue(all(not i.get("covered_by") and not i.get("source_team") for i in items))
		self.assertEqual(rated.payload["subtotal"], 3000)

	def tearDown(self):
		frappe.db.delete("Partner Client Link", {"partner_team": PARTNER_TEAM})
		frappe.db.delete("Partner Client Link", {"client_team": ["in", (CLIENT_TEAM_A, CLIENT_TEAM_B)]})
		frappe.db.delete("Partner Profile", {"team": PARTNER_TEAM})
