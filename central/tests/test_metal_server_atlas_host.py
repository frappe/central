from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.errors import AtlasConnectionError
from central.patches.v0_0 import rename_metal_servers_to_atlas_hosts
from central.tests.utils import ensure_region

REGION = "host-test"
HOSTS = [
	{"id": "h-2", "title": "metal-host-test-2"},
	{"id": "h-3", "title": "metal-host-test-3"},
	{"id": "h-4", "title": "metal-host-test-4"},
]
LIST_HOSTS = "central.integrations.atlas.AtlasClient.list_hosts"


def make_machine(name: str, **fields) -> str:
	frappe.get_doc(
		{
			"doctype": "Metal Server",
			"__newname": name,
			"region": REGION,
			"status": "Active",
			"vendor": "Test",
			"cost_per_month_inr": 1000,
			"vcpus": 8,
			**fields,
		}
	).insert(ignore_permissions=True)
	return name


def host_of(machine: str) -> str | None:
	return frappe.db.get_value("Metal Server", machine, "atlas_host_id")


class TestRenameMetalServersToAtlasHosts(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_region(REGION)

	def test_patch_renames_machines_to_their_host_and_links_it(self):
		make_machine("metal-renamecity-2")
		make_machine("metal-linkedcity-9", atlas_host_id="h-3")
		make_machine("metal-unknowncity-7")
		make_machine("metal-clashcity-4")
		make_machine("metal-host-test-4")

		with patch(LIST_HOSTS, return_value=HOSTS):
			rename_metal_servers_to_atlas_hosts.execute()

		self.assertFalse(frappe.db.exists("Metal Server", "metal-renamecity-2"))
		self.assertEqual(host_of("metal-host-test-2"), "h-2")
		# A machine linked earlier is found by its host ID and takes the host's title.
		self.assertEqual(host_of("metal-host-test-3"), "h-3")
		self.assertTrue(frappe.db.exists("Metal Server", "metal-unknowncity-7"))
		self.assertIsNone(host_of("metal-unknowncity-7"))
		# The host's title is already a machine's name, so the other machine keeps its name and no host.
		self.assertEqual(host_of("metal-host-test-4"), "h-4")
		self.assertIsNone(host_of("metal-clashcity-4"))

	def test_patch_skips_a_region_atlas_cannot_reach(self):
		make_machine("metal-downcity-1")

		with patch(LIST_HOSTS, side_effect=AtlasConnectionError):
			rename_metal_servers_to_atlas_hosts.execute()

		self.assertTrue(frappe.db.exists("Metal Server", "metal-downcity-1"))
		self.assertIsNone(host_of("metal-downcity-1"))
