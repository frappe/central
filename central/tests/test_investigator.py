from unittest.mock import patch

import frappe
from frappe.flow import ToolContext
from frappe.tests import IntegrationTestCase

from central.investigator.tools import read_pilot_api
from central.tests.test_iam import ensure_user

OPERATOR = ToolContext(session_id="test", agent="Central Investigator", user="Administrator")


class TestReadPilotApi(IntegrationTestCase):
	def test_reads_an_allowed_path_and_scrubs_the_result(self):
		with patch(
			"central.investigator.tools.read_pilot", return_value={"db_password": "x", "status": "ok"}
		) as read:
			result = read_pilot_api(
				server="vm-1", path="/api/v1/tasks", params={"status": "failed"}, ctx=OPERATOR
			)

		read.assert_called_once_with("vm-1", "/api/v1/tasks", {"status": "failed"})
		self.assertEqual(result, {"db_password": "[REDACTED]", "status": "ok"})

	def test_scrubs_text_output_before_it_keeps_the_end(self):
		# The last 20000 characters start inside the secret: "rd=hunter22 ...".
		output = "x" * 30000 + " --password=hunter22 " + "y" * (20000 - len("rd=hunter22 "))
		with patch("central.investigator.tools.read_pilot", return_value=output):
			result = read_pilot_api(server="vm-1", path="tasks/abc-1/output/content", ctx=OPERATOR)

		self.assertNotIn("hunter22", result)
		self.assertEqual(len(result), 20000)

	def test_refuses_paths_that_return_secrets_or_files(self):
		for path in (
			"sites/site.local/configuration",
			"sites/site.local/backups/20261028/download-links",
			"sites/site.local/central/frappe.client.get",
			"editor/file",
			"sites/../editor/file",
			"tasks/abc/cancel",
		):
			with self.subTest(path=path), patch("central.investigator.tools.read_pilot") as read:
				with self.assertRaises(frappe.PermissionError):
					read_pilot_api(server="vm-1", path=path, ctx=OPERATOR)
				read.assert_not_called()

	def test_refuses_a_user_who_is_not_an_operator(self):
		user = ensure_user("investigator.member@example.test")
		context = ToolContext(session_id="test", agent="Central Investigator", user=user)

		with patch("central.investigator.tools.read_pilot") as read:
			with self.assertRaises(frappe.PermissionError):
				read_pilot_api(server="vm-1", path="health", ctx=context)
			read.assert_not_called()
