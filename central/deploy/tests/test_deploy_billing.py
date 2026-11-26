from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.catalog.pricing import set_catalog_rate
from central.billing.tests.utils import (
	BillingTestCase,
	complete_billing_profile,
	ensure_team,
	give_team_a_card,
	make_billing_subscription,
	make_plan,
	set_team_tier,
)
from central.deploy.billing import get_plan_specs, get_size_plan, update_vm_plan, validate_vm_resize


def make_size(title: str, vcpus: float, memory: float, disk: float) -> str:
	return make_plan(
		f"deploy-size-{title.lower()}",
		title=title,
		includes=[
			{"resource_type": "Compute", "quantity": vcpus, "unit": "vCPU"},
			{"resource_type": "Memory", "quantity": memory, "unit": "GB"},
			{"resource_type": "Disk", "quantity": disk, "unit": "GB"},
		],
	)


def catalog(*rows: tuple[str, str]) -> dict:
	return {"plans": {"General": [{"plan": plan, "title": title} for plan, title in rows]}}


class IntegrationTestDeployBilling(IntegrationTestCase):
	def test_a_plans_size_is_given_in_atlas_units(self):
		plan = make_size("Starter", 0.5, 2, 25)
		self.assertEqual(get_plan_specs(plan), {"cpu_millicores": 500, "memory_mib": 2048, "disk_mib": 25600})

	def test_a_size_is_the_sellable_plan_with_that_title(self):
		with patch(
			"central.deploy.billing.get_server_plans",
			return_value=catalog(("p1", "Starter"), ("p2", "Growth")),
		):
			self.assertEqual(get_size_plan("team", "region", "Growth"), "p2")

	def test_an_unknown_size_names_the_sizes_there_are(self):
		with (
			patch(
				"central.deploy.billing.get_server_plans",
				return_value=catalog(("p1", "Starter"), ("p2", "Growth")),
			),
			self.assertRaisesRegex(frappe.ValidationError, "Growth, Starter"),
		):
			get_size_plan("team", "region", "Huge")

	def test_an_existing_vm_is_sized_from_the_resize_catalog_without_its_own_subscription(self):
		with (
			patch(
				"central.deploy.billing.get_server_plans", return_value=catalog(("p1", "Growth"))
			) as get_server_plans,
			patch.object(frappe.db, "get_value", return_value="SUB-1"),
		):
			self.assertEqual(get_size_plan("team", "region", "Growth", "server-1"), "p1")
		get_server_plans.assert_called_once_with(
			"team", cluster="region", exclude_subscription="SUB-1", for_resize=1
		)

	def test_two_plans_with_one_title_are_refused(self):
		with (
			patch(
				"central.deploy.billing.get_server_plans",
				return_value=catalog(("p1", "Growth"), ("p2", "Growth")),
			),
			self.assertRaises(frappe.ValidationError),
		):
			get_size_plan("team", "region", "Growth")


class IntegrationTestDeployResizeBilling(BillingTestCase):
	"""A deploy's move to a plan with a smaller disk keeps the disk, billed like the console's resize."""

	def setUp(self):
		team, region = ensure_team("team-deploy-keep-disk"), "deploy-keep-disk"
		complete_billing_profile(team, currency="INR")
		give_team_a_card(team)
		set_team_tier(team, max_spend=1_000_000)
		set_catalog_rate("Resource Type", "Disk", "INR", 10)
		growth = make_size("Growth", 2, 8, 100)
		self.starter = make_size("Starter", 1, 2, 25)
		frappe.db.set_value("Plan", (growth, self.starter), "sub_category", "General")
		set_catalog_rate("Plan", self.starter, "INR", 500)

		self.subscription = make_billing_subscription(team, region, growth, clear_changes=False)
		self.server = frappe.db.get_value("Subscription", self.subscription, "server_id")
		frappe.db.set_value(
			"Virtual Machine",
			self.server,
			{"status": "Running", "vcpus": 2, "memory_megabytes": 8192, "disk_gigabytes": 100},
		)
		# The catalog a team may resize to is tested with get_size_plan.
		self.enterContext(patch("central.deploy.billing._require_offered_plan"))

	def test_a_smaller_plan_keeps_the_disk_and_bills_the_extra(self):
		validate_vm_resize(self.server, self.starter, 100)
		update_vm_plan(self.server, self.starter, 100)

		subscription = frappe.get_doc("Subscription", self.subscription)
		self.assertEqual(
			{row.resource_type: row.quantity for row in subscription.includes},
			{"Compute": 1, "Memory": 2, "Disk": 100},
		)
		rate = frappe.get_all(
			"Subscription Change",
			filters={"subscription": self.subscription, "change_type": "Plan Changed"},
			pluck="locked_rate",
		)
		# Starter's price plus 75 GB at the disk rate.
		self.assertEqual(rate, [500 + 75 * 10])
		self.assertIsNone(frappe.db.get_value("Virtual Machine", self.server, "plan"))

	def test_a_disk_smaller_than_the_vms_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			validate_vm_resize(self.server, self.starter, 25)
