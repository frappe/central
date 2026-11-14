from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.integrations.metrics import (
	CentralMetrics,
	count_request,
	get_request_group,
	publish_metrics,
	take_request_counts,
)


class TestCentralMetrics(IntegrationTestCase):
	def setUp(self) -> None:
		take_request_counts()

	def test_requests_are_counted_by_group_and_status_class_and_reset_when_read(self) -> None:
		for path, status in (
			("/api/method/central.api.sites.create", 200),
			("/api/method/central.api.sites.create", 503),
			("/api/method/central.api.unknown_module.call", 200),
			("/assets/central/app.js", 200),
		):
			count_request(SimpleNamespace(path=path), SimpleNamespace(status_code=status))

		self.assertEqual(take_request_counts(), {"sites|2xx": 1, "sites|5xx": 1, "other|2xx": 1})
		self.assertEqual(take_request_counts(), {})

	def test_the_request_group_keeps_the_label_set_small(self) -> None:
		self.assertEqual(get_request_group("/api/method/central.api.oidc.token"), "oidc")
		self.assertEqual(get_request_group("/api/v2/document/Team/abc"), "document")
		self.assertEqual(get_request_group("/api/method/frappe.auth.get_logged_user"), "other")
		self.assertIsNone(get_request_group("/dashboard"))

	def test_an_old_open_resource_action_reports_its_age(self) -> None:
		creation = frappe.utils.add_to_date(None, hours=-2)
		with patch(
			"central.integrations.metrics.frappe.get_all",
			side_effect=[
				[frappe._dict(region="bom", resource_type="Site", action="create", creation=creation)],
				[frappe._dict(region="bom", resource_type="Site", action="create", status="Failed")],
			],
		):
			metrics = CentralMetrics()
			metrics.add_resource_actions()

		samples = {sample["metric"]: sample for sample in metrics.samples}
		self.assertGreaterEqual(samples["central_resource_action_oldest_open_seconds"]["value"], 7190)
		finished = samples["central_resource_actions_finished_last_hour"]
		self.assertEqual((finished["value"], finished["labels"]["status"]), (1.0, "Failed"))

	def test_an_email_waits_from_its_send_after(self) -> None:
		created = frappe.utils.add_to_date(None, hours=-5)
		send_after = frappe.utils.add_to_date(None, minutes=-30)
		row = frappe._dict(creation=created, send_after=send_after)
		with (
			patch("central.integrations.metrics.frappe.db.count", return_value=0),
			patch("central.integrations.metrics.frappe.get_all", return_value=[row]),
		):
			metrics = CentralMetrics()
			metrics.add_emails()

		samples = {sample["metric"]: sample["value"] for sample in metrics.samples}
		self.assertAlmostEqual(samples["central_email_oldest_unsent_seconds"], 1800, delta=10)

	def test_webhook_requests_are_counted_by_webhook_and_status(self) -> None:
		rows = [frappe._dict(webhook="vm-state", status="Exhausted")] * 2 + [
			frappe._dict(webhook="vm-state", status="Delivered")
		]
		with patch("central.integrations.metrics.frappe.get_all", return_value=rows):
			metrics = CentralMetrics()
			metrics.add_webhooks()

		counts = {sample["labels"]["status"]: sample["value"] for sample in metrics.samples}
		self.assertEqual(counts, {"Exhausted": 2.0, "Delivered": 1.0})

	def test_a_failed_push_keeps_the_request_counts(self) -> None:
		count_request(
			SimpleNamespace(path="/api/method/central.api.sites.get"), SimpleNamespace(status_code=500)
		)
		with (
			patch("central.integrations.metrics.get_central_telemetry_region", return_value="bom"),
			patch("central.integrations.metrics.send_to_datum", return_value=False),
		):
			publish_metrics()

		self.assertEqual(take_request_counts(), {"sites|5xx": 1})

	def test_every_gauge_collects_on_a_real_site(self) -> None:
		metrics = {sample["metric"] for sample in CentralMetrics().collect()}

		self.assertIn("central_billing_run_oldest_open_seconds", metrics)
		self.assertIn("central_job_queue_length", metrics)
		self.assertIn("central_email_oldest_unsent_seconds", metrics)

	def test_metrics_go_to_the_telemetry_region(self) -> None:
		with (
			patch("central.integrations.metrics.get_central_telemetry_region", return_value="bom"),
			patch("central.integrations.metrics.send_to_datum") as send,
		):
			publish_metrics()

		region, path, payload = send.call_args.args
		self.assertEqual((region, path), ("bom", "/v1/ingest"))
		self.assertTrue(payload["samples"])
