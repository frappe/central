from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api.servers import (
	FALLBACK_FRAPPE_VERSIONS,
	_stamp_frappe_version,
	create_server,
	frappe_versions,
)
from central.billing.tests.utils import complete_billing_profile
from central.central.doctype.asset.asset import Asset
from central.tests.test_iam import ensure_user


class TestFrappeVersion(IntegrationTestCase):
	"""The chosen version is validated against what Atlas can provision, resolved by
	Atlas to a bench image and echoed back, and — once mirrored — survives later Atlas
	events that omit it."""

	def setUp(self):
		frappe.set_user("Administrator")
		# The offered versions come from Atlas; pin them so validation is deterministic
		# and never touches the (dummy) Atlas over the network in these tests.
		versions = patch("central.api.servers._available_versions", return_value=["v15", "v16", "nightly"])
		versions.start()
		self.addCleanup(versions.stop)
		self.owner = ensure_user("version.owner@example.test")
		self.team = frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": "Version Team",
				"owner_user": self.owner,
				"members": [{"user": self.owner, "role": "Owner", "status": "Active"}],
			}
		).insert()
		# create_server now requires a complete billing profile (server-side gate),
		# so the version logic under test is only reached once that's satisfied.
		complete_billing_profile(self.team.name)
		self.region = "fv-region-test"
		if not frappe.db.exists("Region", self.region):
			frappe.get_doc({"doctype": "Region", "region": self.region}).insert()
		if not frappe.db.exists("Atlas Instance", self.region):
			frappe.get_doc(
				{
					"doctype": "Atlas Instance",
					"region": self.region,
					"base_url": f"https://{self.region}.atlas.example.test",
					"status": "Active",
					"api_key": "admin-key",
					"api_secret": "admin-secret",
				}
			).insert()

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_create_rejects_unknown_version_before_atlas(self):
		frappe.set_user(self.owner)
		with self.assertRaises(frappe.ValidationError):
			create_server(team=self.team.name, region=self.region, title="v", frappe_version="v99")

	def test_planless_create_still_records_version(self):
		# Without a plan the billing seam never writes a Pending Asset — create_server
		# must mirror the VM Atlas returned so the provisioned version has a row to land
		# on. Atlas echoes the version it laid down in the create reply.
		vm = {
			"name": "fv-planless-test",
			"team": self.team.name,
			"title": "fv-planless",
			"status": "Pending",
			"vcpus": 1,
			"memory_megabytes": 512,
			"disk_gigabytes": 10,
			"frappe_version": "v16",
		}
		frappe.set_user(self.owner)
		with patch("central.integrations.atlas.AtlasClient.create_vm", return_value=vm):
			create_server(team=self.team.name, region=self.region, title="fv-planless", frappe_version="v16")
		self.assertEqual(frappe.db.get_value("Asset", "fv-planless-test", "frappe_version"), "v16")

	def test_stamp_records_version_on_pending_asset(self):
		frappe.get_doc(
			{
				"doctype": "Asset",
				"resource_id": "fv-stamp-test",
				"team": self.team.name,
				"cluster": self.region,
				"status": "Pending",
			}
		).insert(ignore_permissions=True)

		_stamp_frappe_version("fv-stamp-test", "v15")
		self.assertEqual(frappe.db.get_value("Asset", "fv-stamp-test", "frappe_version"), "v15")

		# A missing asset, empty id, or empty version is a no-op, never an error.
		_stamp_frappe_version("fv-does-not-exist", "v15")
		_stamp_frappe_version(None, "v15")
		_stamp_frappe_version("fv-stamp-test", None)
		self.assertEqual(frappe.db.get_value("Asset", "fv-stamp-test", "frappe_version"), "v15")

	def test_mirror_sets_and_preserves_version(self):
		vm = {
			"name": "fv-vm-test",
			"team": self.team.name,
			"title": "fv-vm",
			"status": "Stopped",
			"vcpus": 1,
			"memory_megabytes": 1024,
			"disk_gigabytes": 20,
		}
		Asset.mirror_vm(self.region, {**vm, "frappe_version": "v16"})
		self.assertEqual(frappe.db.get_value("Asset", "fv-vm-test", "frappe_version"), "v16")

		# A later event without the field (an older Atlas) must not wipe it.
		Asset.mirror_vm(self.region, {**vm, "status": "Running"})
		asset = frappe.get_doc("Asset", "fv-vm-test")
		self.assertEqual(asset.status, "Running")
		self.assertEqual(asset.frappe_version, "v16")


class TestVersionSource(IntegrationTestCase):
	"""frappe_versions() derives the picker from Atlas's active bench images, and
	fails soft to a static set when no Atlas answers."""

	def setUp(self):
		frappe.set_user("Administrator")
		# At least one Active region must exist for the proxy path to be attempted.
		if not frappe.db.exists("Region", "vs-region-test"):
			frappe.get_doc({"doctype": "Region", "region": "vs-region-test"}).insert()
		if not frappe.db.exists("Atlas Instance", "vs-region-test"):
			frappe.get_doc(
				{
					"doctype": "Atlas Instance",
					"region": "vs-region-test",
					"base_url": "https://vs-region-test.atlas.example.test",
					"status": "Active",
					"api_key": "k",
					"api_secret": "s",
				}
			).insert()

	def test_proxies_atlas_when_reachable(self):
		with patch(
			"central.integrations.atlas.AtlasClient.available_frappe_versions",
			return_value=["v15", "v16"],
		):
			self.assertEqual(frappe_versions(), ["v15", "v16"])

	def test_falls_back_when_atlas_errors(self):
		with patch(
			"central.integrations.atlas.AtlasClient.available_frappe_versions",
			side_effect=Exception("atlas down"),
		):
			self.assertEqual(frappe_versions(), list(FALLBACK_FRAPPE_VERSIONS))
