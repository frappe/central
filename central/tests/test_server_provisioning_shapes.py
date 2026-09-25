from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.catalog.server_plans import _profiles
from central.resource_actions import _build_server_configuration, image_shape
from central.server_models import CreateServerInput


class TestServerProvisioningShapes(IntegrationTestCase):
	def composition(self, virtual_cpus):
		return [
			{"resource_type": "Compute", "quantity": virtual_cpus},
			{"resource_type": "Memory", "quantity": 0.5},
			{"resource_type": "Disk", "quantity": 20},
		]

	def test_fractional_cpu_configuration_is_rejected_without_rounding(self):
		for value in (0.125, 0.25, 0.5, 1.5):
			with self.subTest(value=value), self.assertRaises(frappe.ValidationError):
				image_shape(self.composition(value), {"rootfs_size_mib": 8192})

	def test_whole_cpus_allow_sub_gib_memory(self):
		shape = image_shape(self.composition(1), {"rootfs_size_mib": 8192})
		self.assertEqual(shape, {"virtual_cpu_count": 1, "memory_mib": 512, "disk_mib": 20480})

	def test_invalid_cpu_numbers_fail_as_validation_errors(self):
		for value in (0, -1, 33, float("nan"), float("inf")):
			with self.subTest(value=value), self.assertRaises(frappe.ValidationError):
				image_shape(self.composition(value), {"rootfs_size_mib": 8192})

	def test_plan_must_fit_image_disk(self):
		with self.assertRaises(frappe.ValidationError):
			image_shape(self.composition(1), {"rootfs_size_mib": 20481})

	def test_profile_without_whole_cpu_steps_is_not_offered(self):
		rows = [
			frappe._dict(name="small", ram_ratio=4, vcpu_steps="0.125,0.25,0.5", disk_min=10, disk_max=100),
			frappe._dict(name="mixed", ram_ratio=4, vcpu_steps="0.5,1,2", disk_min=10, disk_max=100),
		]
		with patch("central.billing.api.dashboard.catalog.frappe.get_all", return_value=rows):
			profiles = _profiles(["Server"])

		self.assertEqual([profile["sub_category"] for profile in profiles], ["mixed"])
		self.assertEqual(profiles[0]["vcpu_steps"], [1, 2])

	def test_saved_keys_are_checked_but_only_their_ids_are_stored(self):
		"""Dispatch reads the key text, so a rotation before a retry sends the current key."""
		server_input = CreateServerInput.model_validate(
			{
				"team": "team-a",
				"region": "region-a",
				"title": "worker",
				"offering": "ubuntu",
				"image_id": "image-a",
				"request_key": "request-key-00000001",
				"plan": "plan-a",
				"ssh_key_ids": ["key-a"],
			}
		)
		image = {"tags": {"os": "Ubuntu"}, "rootfs_size_mib": 8192}
		with (
			patch("central.resource_actions.selected_image", return_value=image),
			patch(
				"central.resource_actions.validate_purchase",
				return_value=(
					[
						{"resource_type": "Compute", "quantity": 1, "unit": "vCPU"},
						{"resource_type": "Memory", "quantity": 1, "unit": "GB"},
						{"resource_type": "Disk", "quantity": 20, "unit": "GB"},
					],
					10.0,
				),
			),
			patch(
				"central.resource_actions.resolve_team_ssh_keys", return_value=["ssh-ed25519 AAAA"]
			) as resolve,
			patch("central.resource_actions.get_team_currency", return_value="USD"),
			patch("central.resource_actions.frappe.db.get_value", return_value="Monthly"),
		):
			configuration, _rate = _build_server_configuration(server_input, None)

		resolve.assert_called_once_with("team-a", ["key-a"])
		self.assertEqual(configuration.ssh_key_ids, ["key-a"])
		self.assertEqual(configuration.ssh_keys, [])
