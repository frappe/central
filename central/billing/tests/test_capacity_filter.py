from unittest import TestCase
from unittest.mock import patch

from central.integrations.images import eligible_plans


def plan(name, disk):
	return {"plan": name, "includes": [{"resource_type": "Disk", "quantity": disk, "unit": "GB"}]}


class TestImagePlanCompatibility(TestCase):
	def test_image_disk_filters_presets_and_custom_steps(self):
		catalog = {
			"plans": {"General": [plan("small", 10), plan("fit", 20)]},
			"profiles": [{"disk_min": 1, "disk_steps": [10, 20, 40]}],
			"capacity": {"gated": False, "available": True, "unmeasured": True, "largest_vm": None},
		}
		with (
			patch("central.integrations.images.selected_image", return_value={"rootfs_size_mib": 15361}),
			patch("central.billing.catalog.server_plans.get_server_plans", return_value=catalog),
		):
			result = eligible_plans("team", "region", "pilot", "image")
		self.assertEqual([row["plan"] for row in result["plans"]["General"]], ["fit"])
		self.assertEqual(result["profiles"], [{"disk_min": 16, "disk_steps": [20, 40]}])
		self.assertEqual(result["image_id"], "image")
		self.assertTrue(result["capacity"]["unmeasured"])
		self.assertFalse(result["capacity"]["gated"])
