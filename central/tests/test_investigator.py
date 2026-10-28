from unittest.mock import patch

import frappe
from frappe.flow import ToolContext
from frappe.tests import IntegrationTestCase

from central.investigator.access import read_write_key
from central.investigator.actions import call_central_api, switch_to_read_write
from central.investigator.tools import (
	get_performance_snapshot,
	run_database_query,
	send_pilot_read_request,
	send_pilot_write_request,
)
from central.tests.test_iam import ensure_user

OPERATOR = ToolContext(session_id="test", agent="Central Investigator", user="Administrator")


class TestReadPilotApi(IntegrationTestCase):
	def test_reads_an_allowed_path_and_scrubs_the_result(self):
		with patch(
			"central.investigator.tools.read_pilot", return_value={"db_password": "x", "status": "ok"}
		) as read:
			result = send_pilot_read_request(
				server="vm-1", path="/api/v1/tasks", params={"status": "failed"}, ctx=OPERATOR
			)

		read.assert_called_once_with("vm-1", "/api/v1/tasks", {"status": "failed"})
		self.assertEqual(result, {"db_password": "[REDACTED]", "status": "ok"})

	def test_scrubs_text_output_before_it_keeps_the_end(self):
		# The last 20000 characters start inside the secret: "rd=hunter22 ...".
		output = "x" * 30000 + " --password=hunter22 " + "y" * (20000 - len("rd=hunter22 "))
		with patch("central.investigator.tools.read_pilot", return_value=output):
			result = send_pilot_read_request(server="vm-1", path="tasks/abc-1/output/content", ctx=OPERATOR)

		self.assertNotIn("hunter22", result)
		self.assertEqual(len(result), 20000)

	def test_refuses_paths_that_return_secrets_or_files(self):
		for path in (
			"sites/site.local/configuration",
			"sites/site.local/backups/20261028/download-links",
			"sites/site.local/central/frappe.client.get",
			"editor/file",
			"sites/../editor/file",
			"sites/site.local/backups/20261028/files/database/content",
			"settings",
		):
			with self.subTest(path=path), patch("central.investigator.tools.read_pilot") as read:
				with self.assertRaises(frappe.PermissionError):
					send_pilot_read_request(server="vm-1", path=path, ctx=OPERATOR)
				read.assert_not_called()

	def test_refuses_a_user_who_is_not_an_operator(self):
		user = ensure_user("investigator.member@example.test")
		context = ToolContext(session_id="test", agent="Central Investigator", user=user)

		with patch("central.investigator.tools.read_pilot") as read:
			with self.assertRaises(frappe.PermissionError):
				send_pilot_read_request(server="vm-1", path="health", ctx=context)
			read.assert_not_called()


class TestPerformanceReads(IntegrationTestCase):
	def test_keeps_performance_data_exact(self):
		processlist = [{"info": "SELECT * FROM tabUser WHERE api_key = 'abc'", "time": 42}]
		with patch("central.investigator.tools.read_pilot", return_value=processlist):
			result = send_pilot_read_request(server="vm-1", path="database/processlist", ctx=OPERATOR)

		self.assertEqual(result, processlist)

	def test_snapshot_keeps_reading_after_one_path_fails(self):
		def read(server, path, params):
			if path.endswith("lockwaits"):
				raise ConnectionError("lockwaits unavailable")
			return {"path": path}

		with patch("central.investigator.tools.read_pilot", side_effect=read):
			snapshot = get_performance_snapshot(server="vm-1", site="site.local", ctx=OPERATOR)

		self.assertEqual(snapshot["database/lockwaits"], {"error": "lockwaits unavailable"})
		self.assertEqual(
			snapshot["sites/site.local/monitoring"], {"path": "/api/v1/sites/site.local/monitoring"}
		)
		self.assertIn("database/performance-report/full_table_scan_queries", snapshot)

	def test_runs_a_select_read_only_with_a_time_limit(self):
		with patch("central.investigator.tools.write_pilot", return_value={"rows": []}) as write:
			run_database_query(
				server="vm-1", site="site.local", query="SELECT name FROM tabToDo;", ctx=OPERATOR
			)

		write.assert_called_once_with(
			"vm-1",
			"POST",
			"/api/v1/database/queries",
			{
				"site": "site.local",
				"query": "SET STATEMENT max_statement_time=10 FOR SELECT name FROM tabToDo",
				"read_only": True,
			},
		)

	def test_refuses_a_query_that_can_change_data_or_read_passwords(self):
		for query in (
			"DROP TABLE tabToDo",
			"UPDATE tabToDo SET status = 'Closed'",
			"SELECT 1; DROP TABLE tabToDo",
			"SELECT * FROM tabToDo INTO OUTFILE '/tmp/x'",
			"SELECT * FROM __Auth",
		):
			with self.subTest(query=query), patch("central.investigator.tools.write_pilot") as write:
				with self.assertRaises(frappe.PermissionError):
					run_database_query(server="vm-1", site="site.local", query=query, ctx=OPERATOR)
				write.assert_not_called()


class TestWriteRequests(IntegrationTestCase):
	def tearDown(self):
		frappe.cache.delete_value(read_write_key(OPERATOR))

	def test_refuses_a_change_in_a_read_only_session(self):
		with patch("central.investigator.tools.write_pilot") as write:
			with self.assertRaises(frappe.PermissionError):
				send_pilot_write_request(
					server="vm-1", method="POST", path="sites/site.local/actions/clear-cache", ctx=OPERATOR
				)
			write.assert_not_called()

	def test_sends_an_allowed_change_after_the_switch(self):
		switch_to_read_write(reason="Clear the stale cache.", ctx=OPERATOR)
		with patch("central.investigator.tools.write_pilot", return_value={"task_id": "t-1"}) as write:
			result = send_pilot_write_request(
				server="vm-1",
				method="POST",
				path="/api/v1/sites/site.local/actions/clear-cache",
				ctx=OPERATOR,
			)

		write.assert_called_once_with("vm-1", "POST", "/api/v1/sites/site.local/actions/clear-cache", None)
		self.assertEqual(result, {"task_id": "t-1"})

	def test_refuses_destruction_and_credentials_after_the_switch(self):
		switch_to_read_write(reason="Test.", ctx=OPERATOR)
		for path in (
			"sites/site.local/actions/reinstall",
			"sites/site.local/actions/restore",
			"database/binlogs/purge",
			"sites/site.local/login",
			"sites/site.local/central/frappe.client.delete",
			"editor/file",
			"auth/password",
			"database/queries",
			"sites/../editor/file",
		):
			with self.subTest(path=path), patch("central.investigator.tools.write_pilot") as write:
				with self.assertRaises(frappe.PermissionError):
					send_pilot_write_request(server="vm-1", method="POST", path=path, ctx=OPERATOR)
				write.assert_not_called()

		for method in ("central.api.servers.terminate_server", "central.api.servers.open_console"):
			with self.subTest(method=method), self.assertRaises(frappe.PermissionError):
				call_central_api(method=method, ctx=OPERATOR)

	def test_an_auto_approved_session_stays_read_only(self):
		with patch("central.investigator.access.frappe.db.get_value", return_value=1):
			with self.assertRaises(frappe.PermissionError):
				switch_to_read_write(reason="Test.", ctx=OPERATOR)
