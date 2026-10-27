from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.catalog.server_plans import get_server_plans
from central.billing.tests.utils import make_plan
from central.resource_actions import image_shape, validate_purchase
from central.site_provisioning import create_trial_site, get_cheapest_trial_plan


class TestTrialPlanSelection(IntegrationTestCase):
	"""Signup uses marked trial plans without changing the Team's paid-server catalog."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)
		self.enterContext(patch("frappe.enqueue"))
		self.enterContext(self.change_settings("Central Settings", trial_servers_per_team=3))
		self.team = frappe.get_doc(
			{"doctype": "Team", "team_name": "Production trial", "owner_user": "Administrator"}
		).insert()
		self.team.db_set("is_staging_trial", 0)
		self.small_plan = self.make_plan(6.25, 10)
		self.trial_plan = self.make_plan(50, 100)
		frappe.db.set_value("Plan", self.trial_plan, "available_on_trial", 1)
		self.caps = frappe._dict(
			max_spend=1000,
			allowed_plans=[self.small_plan, self.trial_plan],
			allowed_clusters=["par-2"],
			tier="Entry",
		)
		self.enterContext(patch("central.billing.catalog.server_plans.get_team_caps", return_value=self.caps))
		self.enterContext(patch("central.billing.catalog.server_plans.get_team_currency", return_value="INR"))

	def make_plan(self, disk: float, rate: float) -> str:
		return make_plan(
			"trial-plan-" + frappe.generate_hash(length=8),
			includes=[
				{"resource_type": "Compute", "quantity": 0.25, "unit": "vCPU"},
				{"resource_type": "Memory", "quantity": 1, "unit": "GB"},
				{"resource_type": "Disk", "quantity": disk, "unit": "GB"},
			],
			rates=[{"currency": "INR", "cluster": "", "rate": rate}],
		)

	def test_production_product_trial_uses_marked_plan_through_creation_validation(self):
		product = frappe.get_doc(
			{
				"doctype": "Product",
				"product_key": "raven-" + frappe.generate_hash(length=8),
				"title": "Raven",
				"signup_app": "raven",
				"enabled": 1,
			}
		).insert()
		image = {"id": "raven-image", "created_at": 1, "rootfs_size_mib": 25600, "tags": {"app": "raven"}}
		with (
			patch("central.site_provisioning.signup_offering", return_value="pilot"),
			patch("central.site_provisioning.trial_regions", return_value=["par-2"]),
			patch("central.site_provisioning.list_images", return_value={"items": [image]}),
			patch("central.site_provisioning.validated_subdomain", return_value="trial-test"),
			patch("central.site_provisioning.submit_request") as submit,
		):
			create_trial_site(self.team.name, "trial-test", "trial-request-key", product.name)

		self.assertEqual(submit.call_args.kwargs["plan"], self.trial_plan)
		self.assertEqual(submit.call_args.kwargs["image_id"], image["id"])
		includes, _ = validate_purchase(self.team.name, "par-2", self.trial_plan, None, None, True)
		self.assertEqual(image_shape(includes, image)["disk_mib"], 51200)
		self.assertEqual(frappe.db.get_value("Team", self.team.name, "is_staging_trial"), 0)

	def test_a_paid_server_is_never_offered_a_trial_plan(self):
		for catalog in (
			get_server_plans(self.team.name, cluster="par-2"),
			get_server_plans(self.team.name, cluster="par-2", for_resize=1),
		):
			plans = {row["plan"] for rows in catalog["plans"].values() for row in rows}
			self.assertEqual(plans, {self.small_plan})

	def test_staging_team_still_selects_marked_plan(self):
		self.team.db_set("is_staging_trial", 1)
		self.assertEqual(get_cheapest_trial_plan(self.team.name, "par-2"), self.trial_plan)

	def test_no_marked_eligible_plan_does_not_fall_back_to_paid_plan(self):
		frappe.db.set_value("Plan", self.trial_plan, "available_on_trial", 0)
		self.assertIsNone(get_cheapest_trial_plan(self.team.name, "par-2"))

	def test_disabled_trial_plan_is_not_selected(self):
		frappe.db.set_value("Plan", self.trial_plan, "is_active", 0)
		self.assertIsNone(get_cheapest_trial_plan(self.team.name, "par-2"))

	def test_trial_flag_does_not_bypass_team_or_region_eligibility(self):
		self.assertIsNone(get_cheapest_trial_plan(self.team.name, "other-region"))
		self.caps.allowed_plans = [self.small_plan]
		self.assertIsNone(get_cheapest_trial_plan(self.team.name, "par-2"))


class TestConvertedTrialPlanFloor(IntegrationTestCase):
	"""A converted trial server is not offered a plan smaller than the one its trial ran on."""

	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.db.rollback)
		self.trial_plan = self.make_plan(0.5, 1, 1500)
		self.smaller_plan = self.make_plan(0.25, 1, 1000)
		self.bigger_plan = self.make_plan(0.5, 2, 2000)

	def make_plan(self, vcpus: float, memory_gigabytes: float, rate: float) -> str:
		return make_plan(
			"floor-plan-" + frappe.generate_hash(length=8),
			includes=[
				{"resource_type": "Compute", "quantity": vcpus, "unit": "vCPU"},
				{"resource_type": "Memory", "quantity": memory_gigabytes, "unit": "GB"},
				{"resource_type": "Disk", "quantity": 12.5, "unit": "GB"},
			],
			rates=[{"currency": "INR", "cluster": "", "rate": rate}],
		)

	def add_trial(self, state: str) -> str:
		server = "floor-server-" + frappe.generate_hash(length=8)
		frappe.get_doc(
			{
				"doctype": "Site",
				"name": f"{server}.localhost",
				"site_name": f"{server}.localhost",
				"server": server,
				"trial_state": state,
			}
		).db_insert()
		frappe.get_doc(
			{
				"doctype": "Resource Action",
				"name": frappe.generate_hash(length=10),
				"resource_type": "Site",
				"action": "create",
				"team": "floor-team",
				"server": server,
				"correlation_id": frappe.generate_hash(length=32),
				"status": "Succeeded",
				"request_payload": frappe.as_json({"plan": self.trial_plan}),
			}
		).db_insert()
		return server

	def test_the_floor_is_the_plan_a_trial_server_started_on(self):
		from central.signups.trial import get_trial_plan_floor

		floor = {"Compute": 0.5, "Memory": 1, "Disk": 12.5}
		self.assertEqual(get_trial_plan_floor(self.add_trial("Active")), floor)
		self.assertEqual(get_trial_plan_floor(self.add_trial("Converted")), floor)
		self.assertIsNone(get_trial_plan_floor("server-without-trial"))

	def test_the_plan_menu_leaves_out_plans_below_the_floor(self):
		caps = frappe._dict(max_spend=10000, allowed_plans=None, allowed_clusters=None, tier="Entry")
		floor = {"Compute": 0.5, "Memory": 1, "Disk": 12.5}
		with (
			patch("central.billing.catalog.server_plans.get_team_caps", return_value=caps),
			patch("central.billing.catalog.server_plans.get_team_currency", return_value="INR"),
			patch("central.billing.catalog.server_plans._get_trial_plan_floor", return_value=floor),
		):
			menu = get_server_plans("floor-team", exclude_subscription="floor-subscription", for_resize=1)

		offered = {row["plan"] for rows in menu["plans"].values() for row in rows}
		self.assertIn(self.trial_plan, offered)
		self.assertIn(self.bigger_plan, offered)
		self.assertNotIn(self.smaller_plan, offered)
