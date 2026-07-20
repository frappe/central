# Copyright (c) 2026, frappe and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api import resources, sites


class TestListResources(IntegrationTestCase):
	def test_list_resources_includes_sites_with_region(self):
		site = frappe.get_all("Site", fields=["name", "team"], limit=1)
		if not site:
			self.skipTest("No Site available to union.")

		result = resources.list_resources(site[0].team)
		kinds = {r["kind"] for r in result["resources"]}
		names = {r["name"] for r in result["resources"]}

		self.assertIn("site", kinds)
		self.assertIn(site[0].name, names)
		self.assertTrue(all("region" in r for r in result["resources"]))

	def test_list_resources_kind_site_returns_only_sites(self):
		site = frappe.get_all("Site", fields=["name", "team"], limit=1)
		if not site:
			self.skipTest("No Site available.")

		result = resources.list_resources(site[0].team, kind="site")
		self.assertTrue(all(r["kind"] == "site" for r in result["resources"]))

	def test_terminate_site_routes_to_atlas(self):
		rows = frappe.get_all("Site", fields=["name", "cluster"], filters={"status": ["!=", "Terminated"]}, limit=25)
		site = next((r for r in rows if r.cluster and frappe.db.exists("Atlas Instance", r.cluster)), None)
		if not site:
			self.skipTest("No site with a known cluster to terminate.")

		with patch("central.api.sites.AtlasClient") as Client:
			result = sites.terminate_site(site.name)

		Client.return_value.terminate_site.assert_called_once_with(site.name)
		self.assertEqual(result["status"], "Terminating")
