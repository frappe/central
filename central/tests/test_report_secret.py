from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.tests.utils import run_enqueued_inline
from central.errors import CargoConnectionError
from central.integrations.cargo import CargoClient
from central.integrations.grove import GroveClient

SECRET = "a-new-report-secret"


class TestReportSecret(IntegrationTestCase):
	"""A new report secret reaches every host that signs usage reports with it."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		self.started = frappe.utils.now_datetime()
		self.regions = [self.make_region(), self.make_region()]
		self.configured = []
		self.failing = set()
		self.enterContext(
			patch.object(CargoClient, "configure_webhooks", autospec=True, side_effect=self.configure)
		)

	def make_region(self) -> str:
		region = frappe.get_doc(
			{
				"doctype": "Region",
				"region": frappe.generate_hash(length=8),
				"cargo_base_url": "http://cargo.example.test:8000",
				"status": "Active",
				"cargo_status": "Registered",
				"cargo_webhook_secret": f"webhook-{frappe.generate_hash(length=6)}",
			}
		).insert()
		return region.name

	def configure(self, client, webhook_secret, report_secret=None):
		if client.instance.name in self.failing:
			# A host that echoes what it was sent must not put the secret in the log.
			frappe.throw(f"Cargo refused {report_secret}", CargoConnectionError)
		self.configured.append((client.instance.name, webhook_secret, report_secret))

	def set_secret(self, service: str, secret: str = SECRET) -> None:
		doc = frappe.get_doc("Service", service)
		doc.report_secret = secret
		doc.save()

	def errors(self) -> list:
		return frappe.get_all(
			"Error Log",
			filters={"method": ["like", "Report secret not sent%"], "creation": [">=", self.started]},
			fields=["method", "error", "reference_name"],
		)

	def test_a_new_storage_secret_is_queued_to_each_registered_cargo_without_the_secret(self):
		with patch("central.integrations.report_secret.frappe.enqueue") as enqueue:
			self.set_secret("storage")

		regions = {call.kwargs.get("region") for call in enqueue.call_args_list}
		self.assertTrue(set(self.regions) <= regions)
		self.assertTrue(all(call.kwargs["enqueue_after_commit"] for call in enqueue.call_args_list))
		self.assertNotIn(SECRET, repr(enqueue.call_args_list))

	def test_a_save_that_keeps_the_secret_sends_nothing(self):
		self.set_secret("storage")
		with patch("central.integrations.report_secret.frappe.enqueue") as enqueue:
			frappe.get_doc("Service", "storage").save()

		enqueue.assert_not_called()

	def test_each_cargo_gets_the_secret_with_its_own_webhook_secret(self):
		with patch("central.integrations.report_secret.frappe.enqueue", side_effect=run_enqueued_inline):
			self.set_secret("storage")

		sent = {region: (webhook, report) for region, webhook, report in self.configured}
		for region in self.regions:
			webhook = frappe.get_doc("Region", region).get_password("cargo_webhook_secret")
			self.assertEqual(sent[region], (webhook, SECRET))

	def test_one_failing_cargo_does_not_stop_the_others_and_logs_no_secret(self):
		self.failing = {self.regions[0]}
		with patch("central.integrations.report_secret.frappe.enqueue", side_effect=run_enqueued_inline):
			self.set_secret("storage")

		self.assertIn(self.regions[1], [region for region, _webhook, _report in self.configured])
		[error] = [row for row in self.errors() if row.reference_name == self.regions[0]]
		self.assertNotIn(SECRET, error.error)
		self.assertNotIn(SECRET, error.method)

	def test_a_new_ai_secret_is_sent_to_grove(self):
		grove = MagicMock()
		with (
			patch.object(GroveClient, "from_settings", return_value=grove),
			patch("central.integrations.report_secret.frappe.enqueue", side_effect=run_enqueued_inline),
		):
			self.set_secret("ai")

		grove.set_report_secret.assert_called_once_with(SECRET)
		self.assertEqual(self.configured, [])

	def test_a_grove_refusal_is_logged_without_the_secret(self):
		grove = MagicMock()
		grove.set_report_secret.side_effect = frappe.ValidationError(f"bad secret {SECRET}")
		with (
			patch.object(GroveClient, "from_settings", return_value=grove),
			patch("central.integrations.report_secret.frappe.enqueue", side_effect=run_enqueued_inline),
		):
			self.set_secret("ai")

		[error] = [row for row in self.errors() if row.method == "Report secret not sent to Grove"]
		self.assertNotIn(SECRET, error.error)

	def test_the_grove_client_calls_the_control_endpoint(self):
		client = GroveClient("https://grove.example.test", "key", "secret")
		with patch.object(client, "call") as call:
			client.set_report_secret(SECRET)

		call.assert_called_once_with("grove.api.control.set_report_secret", secret=SECRET)
