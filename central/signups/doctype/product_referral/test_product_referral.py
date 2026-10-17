# Copyright (c) 2026, frappe and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from central.signups.doctype.affiliate.test_affiliate import make_affiliate
from central.tests.test_iam import ensure_user


class IntegrationTestProductReferral(IntegrationTestCase):
	"""A team has at most one referral for each product, and one for Frappe Cloud itself."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		self.affiliate = make_affiliate("referral.affiliate@example.test").name
		self.team = self.make_team()
		for product_key in ("referral-raven", "referral-crm"):
			self.make_product(product_key)

	def test_name_is_team_and_product(self):
		referral = self.make_referral("referral-raven")

		self.assertEqual(referral.name, f"{self.team}::referral-raven")
		self.assertEqual(frappe.get_doc("Product Referral", referral.name).product, "referral-raven")

	def test_frappe_cloud_signup_uses_the_fc_key(self):
		self.assertEqual(self.make_referral(None).name, f"{self.team}::fc")

	def test_second_referral_for_the_same_product_is_rejected(self):
		self.make_referral("referral-raven")

		with self.assertRaises(frappe.DuplicateEntryError):
			self.make_referral("referral-raven")

	def test_one_team_can_have_a_referral_for_each_product(self):
		names = [self.make_referral(product).name for product in ("referral-raven", "referral-crm", None)]

		self.assertEqual(frappe.db.count("Product Referral", {"referred_team": self.team}), len(names))

	def make_referral(self, product: str | None) -> "frappe.Document":
		return frappe.get_doc(
			{
				"doctype": "Product Referral",
				"referred_team": self.team,
				"product": product,
				"affiliate": self.affiliate,
			}
		).insert()

	def make_team(self) -> str:
		owner = ensure_user("referral.owner@example.test")
		team = frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": "Referral Team",
				"owner_user": owner,
				"members": [{"user": owner, "role": "Owner", "status": "Active"}],
			}
		)
		return team.insert().name

	def make_product(self, product_key: str) -> None:
		frappe.get_doc(
			{"doctype": "Product", "product_key": product_key, "title": product_key, "signup_app": "raven"}
		).insert()
