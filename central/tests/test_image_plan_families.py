from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.catalog.server_plans import get_server_plans
from central.billing.tests.utils import make_plan


class TestImagePlanFamilies(IntegrationTestCase):
	"""An image offering sells its own plan family and hides plans below its minimum memory."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		self.team = frappe.get_doc(
			{"doctype": "Team", "team_name": "Plan families", "owner_user": "Administrator"}
		).insert()
		self.family = frappe.get_doc(
			{
				"doctype": "Plan Category",
				"category_name": "Bundled " + frappe.generate_hash(length=8),
				"is_active": 1,
				"configurator_builder": "Simple",
				"provision_target": "Server",
				"billing_type": "Fixed",
			}
		).insert()
		self.plain_plan = self.make_plan(memory=1)
		self.small_bundle = self.make_plan(memory=0.5, category=self.family.name)
		self.bundle = self.make_plan(memory=2, category=self.family.name)
		self.offering = self.make_offering(plan_category=self.family.name, minimum_memory_mib=1024)

		plans = [self.plain_plan, self.small_bundle, self.bundle]
		caps = frappe._dict(max_spend=1000, allowed_plans=plans, allowed_clusters=None, tier="Entry")
		self.enterContext(patch("central.billing.catalog.server_plans.get_team_caps", return_value=caps))
		self.enterContext(patch("central.billing.catalog.server_plans.get_team_currency", return_value="INR"))

	def make_plan(self, memory: float, **values) -> str:
		return make_plan(
			"family-plan-" + frappe.generate_hash(length=8),
			includes=[
				{"resource_type": "Compute", "quantity": 1, "unit": "vCPU"},
				{"resource_type": "Memory", "quantity": memory, "unit": "GB"},
				{"resource_type": "Disk", "quantity": 25, "unit": "GB"},
			],
			rates=[{"currency": "INR", "cluster": "", "rate": 10}],
			**values,
		)

	def make_offering(self, **values):
		return frappe.get_doc(
			{
				"doctype": "Image Offering",
				"offering_key": "family-" + frappe.generate_hash(length=8).lower(),
				"title": "Bundled",
				"available_in": "Server",
				"required_tags": [{"key": "purpose", "value": "pilot"}],
				**values,
			}
		).insert()

	def offered(self, **arguments) -> set[str]:
		catalog = get_server_plans(self.team.name, **arguments)
		return {row["plan"] for rows in catalog["plans"].values() for row in rows}

	def test_an_offering_sells_only_its_family_above_its_minimum_memory(self):
		self.assertEqual(self.offered(offering=self.offering.name), {self.bundle})

	def test_an_offering_without_a_family_sells_every_server_plan(self):
		open_offering = self.make_offering()

		self.assertLessEqual(
			{self.plain_plan, self.small_bundle, self.bundle}, self.offered(offering=open_offering.name)
		)

	def test_a_family_without_profiles_has_no_custom_sizes(self):
		self.assertEqual(get_server_plans(self.team.name, offering=self.offering.name)["profiles"], [])

	def test_a_server_menu_uses_the_offering_of_the_server(self):
		get_value = frappe.db.get_value

		def get_server_offering(doctype, *args, **kwargs):
			if doctype == "Virtual Machine":
				return self.offering.name
			return get_value(doctype, *args, **kwargs)

		with patch.object(frappe.db, "get_value", side_effect=get_server_offering):
			offered = self.offered(server="server-on-the-bundle", for_resize=1)

		self.assertEqual(offered, {self.bundle})

	def test_a_custom_size_must_be_in_the_family_and_reach_the_minimum_memory(self):
		with self.assertRaises(frappe.ValidationError):
			self.offering.validate_custom_size("General", 4)

		open_offering = self.make_offering(minimum_memory_mib=1024)
		open_offering.validate_custom_size("General", 1)
		with self.assertRaises(frappe.ValidationError):
			open_offering.validate_custom_size("General", 0.5)

	def test_a_server_keeps_the_profile_it_runs(self):
		self.offering.validate_custom_size("General", 4, is_current=True)

	def test_the_family_must_provision_a_server(self):
		self.family.db_set("provision_target", "Resource")

		with self.assertRaises(frappe.ValidationError):
			self.make_offering(plan_category=self.family.name)
