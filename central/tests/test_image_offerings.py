import json
from unittest.mock import patch

import frappe
import requests
from frappe.tests import IntegrationTestCase

from central.errors import AtlasConnectionError
from central.integrations.images import list_images, list_offerings
from central.patches.v0_0.seed_image_offerings import execute as seed_offerings


class TestImageOfferings(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)
		region = frappe.get_doc({"doctype": "Region", "region": frappe.generate_hash(length=8)}).insert()
		self.instance = frappe.get_doc(
			{
				"doctype": "Atlas Instance",
				"region": region.name,
				"base_url": "https://atlas.example.test",
				"atlas_region_id": "43",
				"status": "Active",
			}
		).insert()
		self.team = frappe.get_doc(
			{"doctype": "Team", "team_name": "Image test", "owner_user": "Administrator"}
		).insert()
		self.offering = self.make_offering()
		self.enterContext(patch("central.integrations.atlas.mint_atlas_token", return_value="test-token"))
		self.request = self.enterContext(patch("central.integrations.atlas.requests.request"))
		self.set_page([self.image()])

	def make_offering(self, **values):
		return frappe.get_doc(
			{
				"doctype": "Image Offering",
				"offering_key": "test-" + frappe.generate_hash(length=8),
				"title": "Pilot",
				"enabled": 1,
				"available_in": "Both",
				"required_tags": [{"key": "purpose", "value": "pilot"}],
				**values,
			}
		).insert()

	def image(self, **values):
		return {
			"id": "pilot-16",
			"title": "Pilot Frappe 16",
			"image_type": "system",
			"enabled": True,
			"status": "available",
			"architecture": "amd64",
			"rootfs_size_mib": 8192,
			"created_at": 1789000000,
			"tags": {"purpose": "pilot", "pilot_version": "v1", "frappe_version": "version-16"},
			**values,
		}

	def set_page(self, items, **values):
		response = requests.Response()
		response.status_code = 200
		response._content = json.dumps(
			{"items": items, "has_more": False, "offset": 0, "limit": 100, **values}
		).encode()
		self.request.return_value = response

	def discover(self, **values):
		return list_images(self.team.name, self.instance.name, self.offering.name, **values)

	def test_discovery_uses_system_filter_and_saved_tags(self):
		self.assertEqual(self.discover()["items"][0]["id"], "pilot-16")
		params = self.request.call_args.kwargs["params"]
		self.assertEqual(params, {"image_type": "system", "tag": "purpose:pilot", "offset": 0, "limit": 100})
		self.assertEqual(self.request.call_args.kwargs["headers"]["X-Tenant-ID"], str(self.team.tenant_id))

	def test_filtered_empty_page_preserves_next_page(self):
		self.set_page([self.image(status="uploading", rootfs_size_mib=0)], has_more=True)
		self.assertEqual(self.discover(), {"items": [], "next_offset": 100})
		self.set_page([self.image()], offset=100)
		self.assertEqual(self.discover(offset=100)["items"][0]["id"], "pilot-16")
		self.assertEqual(self.request.call_args.kwargs["params"]["offset"], 100)

	def test_disabled_images_are_not_offered(self):
		self.set_page([self.image(enabled=False)])
		self.assertEqual(self.discover()["items"], [])

	def test_private_or_mismatched_images_fail_closed(self):
		for values in ({"image_type": "machine"}, {"tags": {"purpose": "base"}}, {"tags": []}):
			self.set_page([self.image(**values)])
			with self.subTest(values=values), self.assertRaises(AtlasConnectionError):
				self.discover()

	def test_malformed_image_and_pagination_fail_closed(self):
		for image in (
			None,
			self.image(id=None),
			self.image(enabled=1),
			self.image(rootfs_size_mib=-1),
			self.image(created_at=0),
		):
			self.set_page([image])
			with self.subTest(image=image), self.assertRaises(AtlasConnectionError):
				self.discover()

		for values in ({"offset": 100}, {"limit": 0}, {"has_more": "yes"}, {"has_more": True}):
			self.set_page([], **values)
			with self.subTest(values=values), self.assertRaises(AtlasConnectionError):
				self.discover()

	def test_disabled_offering_and_wrong_flow_do_not_contact_atlas(self):
		self.offering.db_set("enabled", 0)
		with self.assertRaises(frappe.ValidationError):
			self.discover()
		self.offering.db_set({"enabled": 1, "available_in": "Server"})
		with self.assertRaises(frappe.ValidationError):
			self.discover(flow="Signup")
		with self.assertRaises(frappe.ValidationError):
			self.discover(flow="unknown")
		self.request.assert_not_called()

	def test_draining_region_does_not_offer_new_servers(self):
		self.instance.db_set("status", "Draining")
		with self.assertRaises(frappe.ValidationError):
			self.discover()
		self.request.assert_not_called()

	def test_bad_offset_does_not_contact_atlas(self):
		for offset in (-1, True, "100"):
			with self.subTest(offset=offset), self.assertRaises(frappe.ValidationError):
				self.discover(offset=offset)
		self.request.assert_not_called()

	def test_selectors_reject_duplicates_and_query_separators(self):
		for tags in (
			[],
			[{"key": "purpose", "value": ""}],
			[{"key": "purpose", "value": "pilot,os:Ubuntu"}],
			[{"key": "purpose", "value": "pilot"}, {"key": "purpose", "value": "base"}],
		):
			with self.subTest(tags=tags), self.assertRaises(frappe.ValidationError):
				self.make_offering(required_tags=tags)

	def test_offering_key_is_immutable(self):
		self.offering.offering_key = "renamed"
		with self.assertRaises(frappe.ValidationError):
			self.offering.save()

	def test_seed_is_idempotent_and_preserves_operator_changes(self):
		seed_offerings()
		frappe.db.set_value("Image Offering", "pilot", {"title": "Our Pilot", "enabled": 0})
		seed_offerings()
		self.assertEqual(
			frappe.db.get_value("Image Offering", "pilot", ["title", "enabled"]), ("Our Pilot", 0)
		)
		self.assertEqual(
			frappe.get_doc("Image Offering", "ubuntu").get_image_tags(), {"purpose": "base", "os": "Ubuntu"}
		)

	def test_customer_can_read_catalog_but_not_edit_or_preview_as_operator(self):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": f"images-{frappe.generate_hash(length=8)}@example.test",
				"first_name": "Images",
				"send_welcome_email": 0,
				"roles": [{"role": "Central User"}],
			}
		).insert()
		own = frappe.get_doc({"doctype": "Team", "team_name": "Customer", "owner_user": user.name}).insert()
		frappe.set_user(user.name)

		self.assertIn(self.offering.name, [item["name"] for item in list_offerings(own.name)])
		list_images(own.name, self.instance.name, self.offering.name)
		for operation in (
			lambda: self.discover(),
			lambda: list_offerings(self.team.name),
			lambda: self.offering.check_permission("write"),
			lambda: self.offering.check_permission("delete"),
			lambda: self.offering.preview_images(self.instance.name),
			lambda: self.make_offering(),
		):
			with self.assertRaises(frappe.PermissionError):
				operation()
		self.request.assert_called_once()

	def test_operator_preview_reads_saved_selector(self):
		self.offering.required_tags[0].value = "unsaved"
		self.offering.preview_images(self.instance.name)
		self.assertEqual(self.request.call_args.kwargs["params"]["tag"], "purpose:pilot")
