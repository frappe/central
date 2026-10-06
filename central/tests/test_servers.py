# Copyright (c) 2026, frappe and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api import servers
from central.infrastructure.doctype.virtual_machine.virtual_machine import VirtualMachine
from central.tests.test_iam import ensure_user
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
				"region": self.cluster,
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


class TestServerHostnames(IntegrationTestCase):
	"""server_hostnames() lists what a server answers, so terminate can say what stops working."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		self.enterContext(patch.object(VirtualMachine, "ensure_subscription_enabled"))
		frappe.db.set_single_value("Central Settings", "wildcard_domain", "example.test")
		self.zone = "hostnames.example.test"
		self.cluster = ensure_atlas_instance("test-hostnames", proxy_domain=self.zone)
		self.team = (
			frappe.get_doc({"doctype": "Team", "team_name": "Hostnames", "owner_user": "Administrator"})
			.insert()
			.name
		)
		self.server = frappe.get_doc(
			{
				"doctype": "Virtual Machine",
				"resource_id": "server-hostnames",
				"team": self.team,
				"region": self.cluster,
				"status": "Running",
			}
		).insert()

	def test_lists_the_site_and_its_custom_domains(self):
		site = frappe.get_doc(
			{
				"doctype": "Site",
				"site_name": f"erp.{self.zone}",
				"team": self.team,
				"server": self.server.name,
			}
		).insert(ignore_permissions=True)
		for domain in (f"erp.{self.zone}", "shop.example.com"):
			frappe.get_doc(
				{
					"doctype": "Site Domain",
					"domain": domain,
					"team": self.team,
					"region": self.cluster,
					"server": self.server.name,
				}
			).insert(ignore_permissions=True)

		hostnames = servers.server_hostnames(self.team, self.server.resource_id)

		self.assertEqual(
			hostnames,
			[
				{"hostname": site.name, "kind": "Site"},
				{"hostname": "shop.example.com", "kind": "Custom domain"},
			],
		)

	def test_a_user_outside_the_team_is_refused(self):
		frappe.set_user(ensure_user("hostnames.outsider@example.test"))
		try:
			with self.assertRaises(frappe.PermissionError):
				servers.server_hostnames(self.team, self.server.resource_id)
		finally:
			frappe.set_user("Administrator")
