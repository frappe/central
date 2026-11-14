import json
from datetime import datetime
from unittest.mock import patch

import frappe
import requests
from frappe.tests import IntegrationTestCase

from central.integrations.datum import (
	CURSOR_KEY,
	ErrorLogPublisher,
	get_central_telemetry_region,
	to_log_line,
)
from central.tests.utils import ensure_region

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

	def test_a_failed_first_push_keeps_the_first_cursor(self) -> None:
		frappe.cache.delete_value(CURSOR_KEY)
		self.addCleanup(frappe.cache.delete_value, CURSOR_KEY)
		frappe.log_error("Central telemetry first push test")
		with (
			patch("central.integrations.datum.get_telemetry_base_url", return_value="https://datum.test"),
			patch("central.integrations.datum.region_id_of", return_value=1),
			patch("central.integrations.datum.mint_datum_token", return_value="token"),
			patch("central.integrations.datum.requests.post", side_effect=requests.ConnectionError("down")),
		):
			ErrorLogPublisher("any").publish()
			first_cursor = frappe.cache.get_value(CURSOR_KEY)
			ErrorLogPublisher("any").publish()

		self.assertTrue(first_cursor)
		self.assertEqual(frappe.cache.get_value(CURSOR_KEY), first_cursor)


class TestCentralTelemetryRegion(IntegrationTestCase):
	def test_central_sends_to_the_region_with_the_checkbox(self) -> None:
		region = frappe.get_doc("Region", ensure_region("telemetry-test-a"))
		region.is_central_telemetry_region = 1
		region.save(ignore_permissions=True)

		self.assertEqual(get_central_telemetry_region(), "telemetry-test-a")

	def test_only_one_region_takes_the_central_telemetry(self) -> None:
		first = frappe.get_doc("Region", ensure_region("telemetry-test-a"))
		first.is_central_telemetry_region = 1
		first.save(ignore_permissions=True)

		second = frappe.get_doc("Region", ensure_region("telemetry-test-b"))
		second.is_central_telemetry_region = 1
		with self.assertRaises(frappe.ValidationError):
			second.save(ignore_permissions=True)
