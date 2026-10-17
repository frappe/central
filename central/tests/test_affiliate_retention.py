from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api.affiliates import get_retention
from central.signups.doctype.affiliate.test_affiliate import make_affiliate
from central.tests.test_iam import ensure_user


class IntegrationTestAffiliateRetention(IntegrationTestCase):
	"""An affiliate sees how long their paying customers keep paying, and when they stop."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		self.addCleanup(frappe.set_user, "Administrator")
		self.affiliate = make_affiliate("retention.affiliate@example.test")
		self.affiliate.approve()
		self.enterContext(patch("central.signups.affiliates.retention.today", return_value="2026-06-15"))

	def test_retention_shows_who_is_active_and_who_kept_paying(self):
		self.customer("Stays", ["2026-03-05", "2026-04-05", "2026-05-05", "2026-06-05"])
		self.customer("Leaves", ["2026-03-07", "2026-04-07"])
		self.customer("Joins Late", ["2026-05-02", "2026-06-02"])
		self.customer("Never Paid", [])

		retention = self.retention()

		self.assertEqual(
			retention["curve"],
			[
				{"month": 1, "customers": 2, "still_paying": 2, "percent": 100},
				{"month": 2, "customers": 2, "still_paying": 1, "percent": 50},
			],
		)
		self.assertEqual(
			{key: retention[key] for key in ("customers", "active_30_days", "active_90_days")},
			{"customers": 3, "active_30_days": 2, "active_90_days": 3},
		)
		self.assertEqual(retention["trend"], [0] * 8 + [2, 2, 2, 2])

	def test_payments_before_the_referral_do_not_count(self):
		self.customer("Old Customer", ["2026-01-05", "2026-02-05", "2026-04-05"], referred_on="2026-03-01")
		self.customer("Old And Gone", ["2026-01-05"], referred_on="2026-03-01")

		retention = self.retention()

		self.assertEqual(retention["customers"], 1)
		self.assertEqual(retention["trend"], [0] * 9 + [1, 0, 0])

	def test_no_customers_yet(self):
		self.assertEqual(
			self.retention(),
			{
				"customers": 0,
				"active_30_days": 0,
				"active_90_days": 0,
				"trend": [0] * 12,
				"curve": [],
			},
		)

	def test_only_an_active_affiliate_has_retention(self):
		frappe.set_user(ensure_user("retention.stranger@example.test"))

		with self.assertRaises(frappe.PermissionError):
			get_retention()

	def retention(self) -> dict:
		frappe.set_user(self.affiliate.user)
		return get_retention()

	def customer(self, label: str, paid_on: list[str], referred_on: str = "2026-03-01") -> None:
		owner = ensure_user(f"retention.{label.lower().replace(' ', '.')}@example.test")
		team = frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": label,
				"owner_user": owner,
				"members": [{"user": owner, "role": "Owner", "status": "Active"}],
			}
		).insert()
		referral = frappe.get_doc(
			{
				"doctype": "Product Referral",
				"referred_team": team.name,
				"affiliate": self.affiliate.name,
			}
		).insert()
		referral.db_set("creation", f"{referred_on} 00:00:00", update_modified=False)
		for day in paid_on:
			invoice = frappe.get_doc(
				{
					"doctype": "Invoice",
					"team": team.name,
					"status": "Paid",
					"invoice_type": "Billable",
					"amount_paid": 10,
					"paid_at": f"{day} 10:00:00",
				}
			)
			invoice.name = f"retention-{frappe.generate_hash(length=8)}"
			# Only the paid row matters here, not the billing that would create it.
			invoice.db_insert()
