# Copyright (c) 2026, frappe and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from central.central.doctype.region.region import MAXIMUM_ATLAS_REGION_ID


class IntegrationTestRegion(IntegrationTestCase):
	"""The Atlas region id: numbered on insert, unique, and inside Atlas's 16 bits."""

	def setUp(self):
		frappe.set_user("Administrator")

	def region(self, name: str, **values) -> "frappe.Document":
		self.addCleanup(frappe.delete_doc, "Region", name, force=True, ignore_permissions=True)

		return frappe.get_doc({"doctype": "Region", "region": name, **values}).insert(ignore_permissions=True)

	def test_a_region_is_numbered_above_the_highest_one_taken(self):
		highest = frappe.get_all("Region", pluck="atlas_region_id", order_by="atlas_region_id desc", limit=1)
		region = self.region("region-numbered")

		self.assertEqual(region.atlas_region_id, (highest[0] if highest else 0) + 1)

	def test_the_id_atlas_reports_is_kept(self):
		"""Atlas is the authority; the number here only stands in until an operator says."""
		region = self.region("region-told", atlas_region_id=4242)

		self.assertEqual(region.atlas_region_id, 4242)

	def test_two_regions_cannot_share_one_atlas_region(self):
		"""The id names the audience of Cargo's Atlas token, so a twin would accept its calls."""
		self.region("region-first", atlas_region_id=4243)

		with self.assertRaises(frappe.UniqueValidationError):
			self.region("region-twin", atlas_region_id=4243)

	def test_an_id_wider_than_the_mesh_address_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.region("region-too-wide", atlas_region_id=MAXIMUM_ATLAS_REGION_ID + 1)
