from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.tests.utils import complete_billing_profile, ensure_team
from central.patches.v0_0.rename_growth_trust_tier_to_emerging import execute


class TestTrustTierRename(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		self.on_level_update = self.enterContext(patch("central.services.ai.on_level_update"))
		# A migrated site already has Emerging, so put the old name back first.
		if frappe.db.exists("Trust Tier Level", "Emerging"):
			frappe.rename_doc("Trust Tier Level", "Emerging", "Growth", force=True)
			frappe.db.set_value("Trust Tier Level", "Growth", "tier", "Growth")
		self.on_level_update.reset_mock()

		self.team = ensure_team("team-trust-tier-rename")
		complete_billing_profile(self.team)
		frappe.db.set_value(
			"Billing Profile", self.team, {"trust_tier_level": "Growth", "trust_tier": "Growth"}
		)

	def test_the_level_and_the_teams_on_it_move_to_emerging(self):
		execute()

		self.assertFalse(frappe.db.exists("Trust Tier Level", "Growth"))
		self.assertEqual(frappe.db.get_value("Trust Tier Level", "Emerging", "tier"), "Emerging")
		self.assertEqual(
			frappe.db.get_value("Billing Profile", self.team, ["trust_tier_level", "trust_tier"]),
			("Emerging", "Emerging"),
		)
		# The level is saved, so its update hook renames the Tier at Grove.
		self.on_level_update.assert_called_once()

	def test_a_site_without_growth_is_left_alone(self):
		execute()
		self.on_level_update.reset_mock()

		execute()

		self.on_level_update.assert_not_called()
