import json
from datetime import datetime
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.integrations.datum import CURSOR_KEY, ErrorLogPublisher, to_log_line

TRACEBACK = 'Traceback (most recent call last):\n  File "app.py", line 1\nValueError: bad plan\n'


class TestErrorLogPublisher(IntegrationTestCase):
	def test_a_log_line_keeps_the_form_data_out(self) -> None:
		row = frappe._dict(
			name="error-1",
			creation=datetime(2026, 11, 14, 5, 0),
			method="central.billing.charge",
			error=TRACEBACK,
			fingerprint="f1",
			trace_id="",
			metadata=json.dumps(
				{
					"type": "background_job",
					"job_name": "central.billing.charge",
					"form_dict": {"card": "secret"},
				}
			),
		)

		line = to_log_line(row)

		self.assertEqual(line["product"], "central")
		self.assertEqual(line["attributes"]["exception"], "ValueError")
		self.assertEqual(line["attributes"]["unhandled"], "1")
		self.assertNotIn("secret", json.dumps(line))

	def test_new_error_logs_are_read_after_the_cursor(self) -> None:
		frappe.cache.delete_value(CURSOR_KEY)
		name = frappe.log_error("Central telemetry cursor test").name

		self.assertIn(name, [row.name for row in ErrorLogPublisher("any").get_new_error_logs()])

	def test_nothing_is_sent_while_the_region_has_no_telemetry_host(self) -> None:
		frappe.log_error("Central telemetry test")
		with (
			patch("central.integrations.datum.get_telemetry_base_url", return_value=None),
			patch("central.integrations.datum.requests.post") as post,
		):
			ErrorLogPublisher("any").publish()

		post.assert_not_called()
