# Copyright (c) 2026, frappe and Contributors
# See license.txt

import re
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.deploy.doctype.deploy_app.deploy_app import DeployApp, get_new_domain
from central.infrastructure.doctype.github_connection.test_github_connection import make_team
from central.infrastructure.doctype.github_installation.test_github_installation import (
	make_installation,
)
from central.infrastructure.doctype.region.region import Region
from central.tests.test_iam import ensure_user
from central.tests.utils import ensure_region

REPOSITORY = {"repository_id": "11", "full_name": "octo/app", "default_branch": "main"}


class IntegrationTestDeployApp(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		# Each test's apps would otherwise share installation 101 with the next test's team.
		frappe.db.savepoint("deploy_app_test")
		self.addCleanup(frappe.db.rollback, save_point="deploy_app_test")
		frappe.db.set_single_value("Central Settings", "wildcard_domain", "example.test")
		owner = ensure_user("deploy.app.owner@example.test")
		self.team = make_team("Deploy App Team", owner)
		self.installation = make_installation(self.team)
		self.region = ensure_region("deploy-app-test")

		app = patch("central.deploy.doctype.deploy_app.deploy_app.GitHubApp").start()
		self.addCleanup(patch.stopall)
		app.return_value.has_branch.side_effect = lambda *args: args[-1] in ("main", "staging")

	def test_a_repository_deploys_from_its_default_branch(self):
		app = DeployApp.add(self.installation, REPOSITORY, self.region)
		self.assertEqual(
			(app.repository, app.repository_id, app.branch, app.installation, app.region),
			("octo/app", "11", "main", self.installation.name, self.region),
		)

	def test_a_new_app_gets_a_domain_named_after_its_repository(self):
		app = DeployApp.add(self.installation, REPOSITORY, self.region)
		self.assertRegex(app.domain, rf"^app-[0-9a-f]{{6}}\.{re.escape(Region.get_zone(self.region))}$")

	def test_adding_the_app_again_keeps_its_domain(self):
		first = DeployApp.add(self.installation, REPOSITORY, self.region).domain
		self.assertEqual(DeployApp.add(self.installation, REPOSITORY, self.region).domain, first)

	def test_an_app_without_a_vm_moving_region_gets_a_domain_there(self):
		other = ensure_region("deploy-app-other")
		DeployApp.add(self.installation, REPOSITORY, self.region)
		self.assertTrue(
			DeployApp.add(self.installation, REPOSITORY, other).domain.endswith(Region.get_zone(other))
		)

	def test_a_domain_label_is_cut_to_fit_dns_and_never_auto_routed(self):
		with patch("central.deploy.doctype.deploy_app.deploy_app.Region.get_zone", return_value="zone.test"):
			long_name = get_new_domain("octo/" + "My_Repo." * 20, "region")
			self.assertLessEqual(len(long_name.split(".")[0]), 63)
			self.assertTrue(long_name.startswith("my-repo-my-repo"))
			self.assertTrue(get_new_domain("octo/site-builder", "region").startswith("app-"))
			self.assertTrue(get_new_domain("octo/my-vm-tools", "region").startswith("app-"))

	def test_one_repository_can_deploy_from_two_branches(self):
		DeployApp.add(self.installation, REPOSITORY, self.region)
		DeployApp.add(self.installation, REPOSITORY, self.region, "staging")
		self.assertEqual(frappe.db.count("Deploy App", {"team": self.team, "repository_id": "11"}), 2)

	def test_adding_the_same_branch_again_keeps_one_app(self):
		first = DeployApp.add(self.installation, REPOSITORY, self.region)
		self.assertEqual(DeployApp.add(self.installation, REPOSITORY, self.region).name, first.name)

	def test_an_app_with_a_vm_cannot_change_region(self):
		app = DeployApp.add(self.installation, REPOSITORY, self.region)
		app.db_set("virtual_machine", "server-deploy-app-test")
		with self.assertRaisesRegex(frappe.ValidationError, "Its region cannot change"):
			DeployApp.add(self.installation, REPOSITORY, ensure_region("deploy-app-other"))

	def test_a_region_change_is_refused_before_the_user_goes_to_github(self):
		app = DeployApp.add(self.installation, REPOSITORY, self.region)
		app.db_set("virtual_machine", "server-deploy-app-test")
		other = ensure_region("deploy-app-other")
		with self.assertRaisesRegex(frappe.ValidationError, "Its region cannot change"):
			DeployApp.validate_region(self.team, "octo/app", "main", other)
		DeployApp.validate_region(self.team, "octo/app", "main", self.region)
		DeployApp.validate_region(self.team, "octo/app", "staging", other)

	def test_a_terminated_server_disables_its_apps(self):
		main = DeployApp.add(self.installation, REPOSITORY, self.region)
		staging = DeployApp.add(self.installation, REPOSITORY, self.region, "staging")
		main.db_set("virtual_machine", "server-1")
		staging.db_set("virtual_machine", "server-2")

		DeployApp.disable_for_server("server-1")
		fields = ["status", "virtual_machine", "domain"]
		self.assertEqual(frappe.db.get_value("Deploy App", main.name, fields), ("Disabled", None, None))
		self.assertEqual(
			frappe.db.get_value("Deploy App", staging.name, fields), ("Active", "server-2", staging.domain)
		)
		self.assertEqual(DeployApp.get_for_push("101", "11", "main"), [])

	def test_connecting_a_disabled_app_again_gives_it_a_new_domain(self):
		app = DeployApp.add(self.installation, REPOSITORY, self.region)
		app.db_set("virtual_machine", "server-1")
		DeployApp.disable_for_server("server-1")

		again = DeployApp.add(self.installation, REPOSITORY, self.region)
		self.assertEqual((again.name, again.status, again.virtual_machine), (app.name, "Active", None))
		self.assertNotEqual(again.domain, app.domain)
		self.assertEqual(DeployApp.get_for_push("101", "11", "main"), [app.name])

	def test_a_branch_missing_on_github_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			DeployApp.add(self.installation, REPOSITORY, self.region, "typo")

	def test_a_push_finds_the_apps_of_its_branch(self):
		main = DeployApp.add(self.installation, REPOSITORY, self.region)
		DeployApp.add(self.installation, REPOSITORY, self.region, "staging")
		self.assertEqual(DeployApp.get_for_push("101", "11", "main"), [main.name])
		self.assertEqual(DeployApp.get_for_push("101", "11", "feature"), [])
		self.assertEqual(DeployApp.get_for_push("202", "11", "main"), [])

		self.installation.status = "Disabled"
		self.installation.save()
		self.assertEqual(DeployApp.get_for_push("101", "11", "main"), [])
