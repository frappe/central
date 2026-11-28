from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.errors import AtlasConnectionError
from central.patches.v0_0 import link_metal_servers_to_atlas_hosts
from central.tests.utils import ensure_region

REGION = "host-test"
HOSTS = [{"id": "h-2", "title": "metal-host-test-2"}, {"id": "h-3", "title": "metal-namedcity-3"}]
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


class TestMetalServerAtlasHost(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_region(REGION)

	def test_patch_fills_only_machines_without_a_host(self):
		make_machine("metal-patchcity-2")
		make_machine("metal-namedcity-3")
		make_machine("metal-patchcity-9")
		make_machine("metal-keptcity-1", atlas_host_id="kept")

		with patch(LIST_HOSTS, return_value=HOSTS):
			link_metal_servers_to_atlas_hosts.execute()

		self.assertEqual(host_of("metal-patchcity-2"), "h-2")  # city name, host titled with the region code
		self.assertEqual(host_of("metal-namedcity-3"), "h-3")  # host titled with the machine name
		self.assertIsNone(host_of("metal-patchcity-9"))
		self.assertEqual(host_of("metal-keptcity-1"), "kept")

	def test_patch_skips_a_region_atlas_cannot_reach(self):
		make_machine("metal-downcity-1")

		with patch(LIST_HOSTS, side_effect=AtlasConnectionError):
			link_metal_servers_to_atlas_hosts.execute()

		self.assertIsNone(host_of("metal-downcity-1"))
