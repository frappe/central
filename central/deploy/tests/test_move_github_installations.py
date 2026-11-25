import frappe
from frappe.tests import IntegrationTestCase

from central.infrastructure.doctype.github_connection.test_github_connection import make_team
from central.infrastructure.doctype.github_installation.test_github_installation import make_installation
from central.patches.v0_0.move_github_installations import move_deploy_installation
from central.tests.test_iam import ensure_user


class IntegrationTestMoveGitHubInstallations(IntegrationTestCase):
	def test_an_installation_of_the_old_deploy_app_is_disabled_with_its_apps(self):
		team = make_team("Move GitHub Installation Team", ensure_user("move.github.owner@example.test"))
		app = frappe.get_doc(
			{
				"doctype": "Deploy App",
				"team": team,
				"installation": make_installation(team, "901").name,
				"repository": "octo/app",
				"repository_id": "11",
				"branch": "main",
			}
		).insert()
		# The app still points at its row in the removed GitHub Deploy App Installation table.
		app.db_set("installation", "old-deploy-installation")

		move_deploy_installation(
			frappe._dict(
				name="old-deploy-installation",
				team=team,
				installation_id="902",
				account="octo",
				account_type="Organization",
			)
		)

		installation, status = frappe.db.get_value("Deploy App", app.name, ["installation", "status"])
		self.assertEqual(
			frappe.db.get_value("GitHub Installation", installation, ["installation_id", "status"]),
			("902", "Disabled"),
		)
		self.assertEqual(status, "Disabled")
