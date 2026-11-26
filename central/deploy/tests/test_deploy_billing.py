from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.tests.utils import make_plan
from central.deploy.billing import get_plan_specs, get_size_plan


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
