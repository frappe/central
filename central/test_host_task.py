# Copyright (c) 2026, frappe and Contributors
# See license.txt

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.host_task import _variables_to_flags, parse_result, prune_host_tasks, run_host_task


def _write_script(body: str) -> str:
	fd, path = tempfile.mkstemp(suffix=".py", prefix="hosttask-test-")
	with os.fdopen(fd, "w") as handle:
		handle.write(body)
	return path


class IntegrationTestHostTask(IntegrationTestCase):
	def test_variables_to_flags(self):
		flags = _variables_to_flags(
			{"PRIVATE_KEY_PATH": "/etc/wireguard/wg0.key", "LISTEN_PORT": 51820, "EMPTY": ""}
		)
		self.assertEqual(flags, "--private-key-path /etc/wireguard/wg0.key --listen-port 51820")

	def test_parse_result_last_marker_wins(self):
		stdout = 'noise\nATLAS_RESULT={"a": 1}\nmore\nATLAS_RESULT={"a": 2}'
		self.assertEqual(parse_result(stdout), {"a": 2})

	def test_parse_result_missing_raises(self):
		with self.assertRaises(ValueError):
			parse_result("no marker here")

	def test_run_host_task_success_records_audit_row(self):
		script = _write_script('import sys\nprint("ATLAS_RESULT=" + \'{"public_key": "K="}\')\nsys.exit(0)\n')
		try:
			with patch("central.host_task.resolve", return_value=Path(script)):
				task = run_host_task(script="hub-up.py", variables={})
		finally:
			os.unlink(script)

		self.assertEqual(task.status, "Success")
		self.assertEqual(task.exit_code, 0)
		self.assertEqual(parse_result(task.stdout), {"public_key": "K="})
		self.assertTrue(frappe.db.exists("Host Task", task.name))

	def test_run_host_task_failure_throws_and_marks_failure(self):
		script = _write_script('import sys\nsys.stderr.write("boom\\n")\nsys.exit(3)\n')
		try:
			with patch("central.host_task.resolve", return_value=Path(script)):
				with self.assertRaises(frappe.ValidationError):
					run_host_task(script="hub-up.py", variables={})
		finally:
			os.unlink(script)

		task = frappe.get_last_doc("Host Task")
		self.assertEqual(task.status, "Failure")
		self.assertEqual(task.exit_code, 3)

	def test_prune_honours_central_settings_window(self):
		frappe.db.set_single_value("Central Settings", "host_task_retention_days", 7)
		self.addCleanup(frappe.db.set_single_value, "Central Settings", "host_task_retention_days", 30)
		script = _write_script('import sys\nprint("ATLAS_RESULT=" + \'{"ok": 1}\')\nsys.exit(0)\n')
		try:
			with patch("central.host_task.resolve", return_value=Path(script)):
				task = run_host_task(script="hub-up.py", variables={})
		finally:
			os.unlink(script)

		# 'now' eight days on: a fresh Success task is past the 7-day window (it would
		# survive the 30-day default, so this proves the window is read from the Single).
		future = frappe.utils.add_to_date(frappe.utils.now_datetime(), days=8)
		prune_host_tasks(now=future)
		self.assertFalse(frappe.db.exists("Host Task", task.name))
