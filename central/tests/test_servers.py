# Copyright (c) 2026, frappe and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from central.api import servers
from central.tests.utils import ensure_atlas_instance


class TestRegistry(IntegrationTestCase):
	"""registry() unifies servers (Asset) and sites (Site) — each a VM — in one read."""

	def _team_and_cluster(self) -> tuple[str, str]:
		frappe.set_user("Administrator")
		team = frappe.get_doc(
			{"doctype": "Team", "team_name": "Registry", "owner_user": "Administrator"}
		).insert()
		return team.name, ensure_atlas_instance("test-registry")

	def _make_site(self, name: str, subdomain: str, status: str, team: str, cluster: str) -> None:
		self.addCleanup(
			lambda: (
				frappe.db.exists("Site", name)
				and frappe.delete_doc("Site", name, ignore_permissions=True, force=True)
			)
		)
		frappe.get_doc(
			{
				"doctype": "Site",
				"site_name": name,
				"subdomain": subdomain,
				"team": team,
				"cluster": cluster,
				"status": status,
			}
		).insert(ignore_permissions=True)

	def test_registry_includes_sites_with_subdomain(self):
		team, cluster = self._team_and_cluster()
		name = "zz-registry-test.example.dev"
		self._make_site(name, "zz-registry-test", "Running", team, cluster)

		result = servers.registry(team)
		sites = {s["name"]: s for s in result["sites"]}

		self.assertIn(name, sites)
		# The display name is the user-entered subdomain, not the FQDN.
		self.assertEqual(sites[name]["subdomain"], "zz-registry-test")

	def test_registry_excludes_terminated_sites(self):
		team, cluster = self._team_and_cluster()
		name = "zz-registry-terminated.example.dev"
		self._make_site(name, "zz-registry-terminated", "Terminated", team, cluster)

		result = servers.registry(team)
		self.assertNotIn(name, {s["name"] for s in result["sites"]})
