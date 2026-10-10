from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from central.infrastructure.doctype.virtual_machine.virtual_machine import MAXIMUM_TITLE_LENGTH


class TestServerRename(UnitTestCase):
	def setUp(self):
		self.server = frappe.new_doc("Virtual Machine")
		self.db_set = self.enterContext(patch.object(self.server, "db_set"))

	def test_rename_stores_the_trimmed_title(self):
		self.assertEqual(self.server.rename("  billing worker  "), "billing worker")
		self.db_set.assert_called_once_with("title", "billing worker")

	def test_rename_refuses_a_blank_or_long_title(self):
		for title in ("", "   ", None, "x" * (MAXIMUM_TITLE_LENGTH + 1)):
			with self.subTest(title=title), self.assertRaises(frappe.ValidationError):
				self.server.rename(title)

		self.db_set.assert_not_called()

	def test_rename_without_the_capability_is_refused(self):
		from central.api.servers import rename_server

		self.enterContext(patch("central.utils.guards.resolve_team", return_value="TEAM-1"))
		self.enterContext(patch("central.utils.guards.can", return_value=False))
		self.enterContext(patch("central.utils.guards.frappe.session", user="user@example.com"))

		with self.assertRaises(frappe.PermissionError):
			rename_server(team="TEAM-1", resource_id="server-1", title="worker")
