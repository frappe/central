# Copyright (c) 2026, frappe and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api import servers
from central.infrastructure.doctype.virtual_machine.virtual_machine import VirtualMachine
from central.tests.utils import ensure_atlas_instance


class TestRegistry(IntegrationTestCase):
	"""registry() unifies servers (VirtualMachine) and sites (Site) — each a VM — in one read."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		self.enterContext(patch.object(VirtualMachine, "ensure_subscription_enabled"))
		self.team = (
			frappe.get_doc({"doctype": "Team", "team_name": "Registry", "owner_user": "Administrator"})
			.insert()
			.name
		)
		self.cluster = ensure_atlas_instance("test-registry")

	def make_site(self, label: str, status: str) -> str:
		machine = frappe.get_doc(
			{
				"doctype": "Virtual Machine",
				"resource_id": f"server-{label}",
				"team": self.team,
				"cluster": self.cluster,
				"status": status,
			}
		).insert()
		return (
			frappe.get_doc(
				{
					"doctype": "Site",
					"site_name": f"{label}.example.dev",
					"team": self.team,
					"server": machine.name,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_a_site_lists_with_the_state_of_the_machine_it_is(self):
		name = self.make_site("zz-registry-test", "Running")

		sites = {row["name"]: row for row in servers.registry(self.team)["sites"]}

		self.assertEqual(sites[name]["status"], "Running")
		self.assertEqual(sites[name]["region"], self.cluster)
		self.assertEqual(sites[name]["url"], f"https://{name}")
		self.assertEqual(sites[name]["subdomain"], "zz-registry-test")

	def test_a_terminated_machine_takes_its_site_out_of_the_fleet(self):
		name = self.make_site("zz-registry-terminated", "Terminated")

		self.assertNotIn(name, {row["name"] for row in servers.registry(self.team)["sites"]})
