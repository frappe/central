from unittest.mock import MagicMock, patch

import frappe
import requests
from frappe.tests import IntegrationTestCase
from frappe.utils.password import set_encrypted_password

from central.billing.tests.utils import run_enqueued_inline
from central.errors import CargoConnectionError
from central.integrations.cargo import CargoClient
from central.integrations.grove import GroveClient
from central.integrations.report_secret import send_to_cargo, send_to_grove
from central.services.doctype.service.service import get_report_secret

SECRET = "a-new-report-secret"
NEWER_SECRET = "a-newer-report-secret"


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
		self.rotate_on_send = None
		self.enterContext(
			patch.object(CargoClient, "configure_webhooks", autospec=True, side_effect=self.configure)
		)
		# A job ends its transaction to see a newer secret. Here that would drop this test's records.
		self.enterContext(patch("central.integrations.report_secret.frappe.db.rollback"))

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
			raise CargoConnectionError(f"Cargo refused {report_secret}")
		self.configured.append((client.instance.name, webhook_secret, report_secret))
		self.rotate("storage")

	def rotate(self, service: str) -> None:
		# Stored directly, as a rotation that commits while a send is in flight.
		if self.rotate_on_send:
			set_encrypted_password("Service", service, self.rotate_on_send, "report_secret")
			self.rotate_on_send = None

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

	def test_a_cargo_with_no_webhook_secret_is_skipped_and_logged(self):
		frappe.db.delete("__Auth", {"doctype": "Region", "name": self.regions[0]})
		with patch("central.integrations.report_secret.frappe.enqueue", side_effect=run_enqueued_inline):
			self.set_secret("storage")

		self.assertNotIn(self.regions[0], [region for region, _webhook, _report in self.configured])
		self.assertIn(self.regions[1], [region for region, _webhook, _report in self.configured])
		self.assertTrue([row for row in self.errors() if row.reference_name == self.regions[0]])

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

	def test_a_secret_rotated_during_a_cargo_send_is_sent_again(self):
		with patch("central.integrations.report_secret.frappe.enqueue"):
			self.set_secret("storage")
		self.rotate_on_send = NEWER_SECRET

		send_to_cargo(self.regions[0])

		sent = [report for _region, _webhook, report in self.configured]
		self.assertEqual(sent, [SECRET, NEWER_SECRET])
		self.assertEqual(sent[-1], get_report_secret("storage"))

	def test_a_secret_rotated_during_a_grove_send_is_sent_again(self):
		with patch("central.integrations.report_secret.frappe.enqueue"):
			self.set_secret("ai")
		self.rotate_on_send = NEWER_SECRET
		grove = MagicMock()
		grove.set_report_secret.side_effect = lambda secret: self.rotate("ai")

		with patch.object(GroveClient, "from_settings", return_value=grove):
			send_to_grove()

		sent = [call.args[0] for call in grove.set_report_secret.call_args_list]
		self.assertEqual(sent, [SECRET, NEWER_SECRET])
		self.assertEqual(sent[-1], get_report_secret("ai"))

	def test_a_secret_that_changes_on_every_send_is_logged_and_sent_by_a_fresh_job(self):
		with patch("central.integrations.report_secret.frappe.enqueue"):
			self.set_secret("ai")
		grove = MagicMock()
		grove.set_report_secret.side_effect = lambda secret: set_encrypted_password(
			"Service", "ai", frappe.generate_hash(length=12), "report_secret"
		)

		with (
			patch.object(GroveClient, "from_settings", return_value=grove),
			patch("central.integrations.report_secret.frappe.enqueue") as enqueue,
		):
			send_to_grove()

		self.assertEqual(grove.set_report_secret.call_count, 3)
		self.assertEqual(
			len([row for row in self.errors() if row.method == "Report secret not sent to Grove"]), 1
		)
		enqueue.assert_called_once()
		self.assertEqual(enqueue.call_args.args, ("central.integrations.report_secret.send_to_grove",))
		self.assertEqual(
			{
				key: enqueue.call_args.kwargs[key]
				for key in ("queue", "enqueue_after_commit", "job_id", "deduplicate")
			},
			{
				"queue": "short",
				"enqueue_after_commit": True,
				"job_id": "report-secret-ai-all",
				"deduplicate": True,
			},
		)
		self.assertNotIn(get_report_secret("ai"), repr(enqueue.call_args))

	def test_a_cargo_secret_that_changes_on_every_send_is_resent_for_that_region(self):
		with patch("central.integrations.report_secret.frappe.enqueue"):
			self.set_secret("storage")
		region = self.regions[0]

		def rotate_each_send(service):
			set_encrypted_password("Service", service, frappe.generate_hash(length=12), "report_secret")

		with (
			patch.object(self, "rotate", side_effect=rotate_each_send),
			patch("central.integrations.report_secret.frappe.enqueue") as enqueue,
		):
			send_to_cargo(region)

		self.assertEqual(len(self.configured), 3)
		self.assertEqual(enqueue.call_args.args, ("central.integrations.report_secret.send_to_cargo",))
		self.assertEqual(enqueue.call_args.kwargs["region"], region)
		self.assertEqual(enqueue.call_args.kwargs["job_id"], f"report-secret-storage-{region}")

	def test_a_secret_sent_as_stored_queues_no_fresh_job(self):
		with patch("central.integrations.report_secret.frappe.enqueue"):
			self.set_secret("storage")
		self.rotate_on_send = NEWER_SECRET

		with patch("central.integrations.report_secret.frappe.enqueue") as enqueue:
			send_to_cargo(self.regions[0])

		enqueue.assert_not_called()

	def test_grove_without_control_credentials_is_logged_without_failing_the_job(self):
		with patch("central.integrations.report_secret.frappe.enqueue"):
			self.set_secret("ai")
		refusal = frappe.ValidationError("AI Settings has no Grove control credentials.")

		with patch.object(GroveClient, "from_settings", side_effect=refusal):
			send_to_grove()

		[error] = [row for row in self.errors() if row.method == "Report secret not sent to Grove"]
		self.assertIn("no Grove control credentials", error.error)
		self.assertNotIn(SECRET, error.error)
		self.assertNotIn("Traceback", error.error)

	def delivery(self, service: str):
		return frappe.db.get_value(
			"Service",
			service,
			["secret_delivery_status", "secret_delivery_error", "secret_delivered_at"],
			as_dict=True,
		)

	def test_grove_not_set_up_shows_failed_on_the_service_without_the_secret(self):
		refusal = frappe.ValidationError(f"AI Settings has no Grove control credentials. {SECRET}")
		with (
			patch.object(GroveClient, "from_settings", side_effect=refusal),
			patch("central.integrations.report_secret.frappe.enqueue", side_effect=run_enqueued_inline),
		):
			self.set_secret("ai")

		delivery = self.delivery("ai")
		self.assertEqual(delivery.secret_delivery_status, "Failed")
		self.assertIn("Grove is not set up", delivery.secret_delivery_error)
		self.assertIn("no Grove control credentials", delivery.secret_delivery_error)
		self.assertNotIn(SECRET, delivery.secret_delivery_error)

	def test_a_successful_cargo_send_shows_delivered(self):
		with patch("central.integrations.report_secret.frappe.enqueue", side_effect=run_enqueued_inline):
			self.set_secret("storage")

		delivery = self.delivery("storage")
		self.assertEqual(delivery.secret_delivery_status, "Delivered")
		self.assertFalse(delivery.secret_delivery_error)
		self.assertGreaterEqual(delivery.secret_delivered_at, self.started.replace(microsecond=0))

	def test_one_failing_region_shows_failed_naming_only_that_region(self):
		self.failing = {self.regions[0]}
		with patch("central.integrations.report_secret.frappe.enqueue", side_effect=run_enqueued_inline):
			self.set_secret("storage")

		delivery = self.delivery("storage")
		self.assertEqual(delivery.secret_delivery_status, "Failed")
		self.assertIn(f"Cargo in region {self.regions[0]}", delivery.secret_delivery_error)
		self.assertNotIn(self.regions[1], delivery.secret_delivery_error)
		self.assertNotIn(SECRET, delivery.secret_delivery_error)

	def test_a_new_secret_clears_the_last_failure(self):
		self.failing = {self.regions[0]}
		with patch("central.integrations.report_secret.frappe.enqueue", side_effect=run_enqueued_inline):
			self.set_secret("storage")
		self.failing = set()

		with patch("central.integrations.report_secret.frappe.enqueue", side_effect=run_enqueued_inline):
			self.set_secret("storage", NEWER_SECRET)

		self.assertEqual(self.delivery("storage").secret_delivery_status, "Delivered")

	def test_the_grove_client_calls_the_control_endpoint(self):
		client = GroveClient("https://grove.example.test", "key", "secret")
		with patch.object(client, "call") as call:
			client.set_report_secret(SECRET)

		call.assert_called_once_with(
			"grove.api.control.set_report_secret", secret_to_hide=SECRET, secret=SECRET
		)


class TestReportSecretNeverLogged(IntegrationTestCase):
	"""A host whose error echoes the request leaves no Error Log holding the secret."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		self.started = frappe.utils.now_datetime()

	def echo(self, *args, json=None, **kwargs) -> requests.Response:
		# Plain text, not a Frappe refusal, so the client logs the body itself.
		response = requests.Response()
		response.status_code = 500
		response._content = f"Internal error handling {json}".encode()
		return response

	def logs(self) -> list:
		return frappe.get_all(
			"Error Log", filters={"creation": [">=", self.started]}, fields=["method", "error"]
		)

	def assert_logged_without_secret(self) -> None:
		logs = self.logs()
		self.assertTrue(logs)
		for log in logs:
			self.assertNotIn(SECRET, f"{log.method} {log.error}")

	def test_a_grove_500_echoing_the_secret_logs_no_secret(self):
		grove = GroveClient("https://grove.example.test", "key", "secret")
		with (
			patch.object(GroveClient, "from_settings", return_value=grove),
			patch("central.integrations.grove.requests.post", side_effect=self.echo),
			patch("central.integrations.report_secret.get_report_secret", return_value=SECRET),
		):
			send_to_grove()

		self.assertIn("Grove request failed", [log.method for log in self.logs()])
		self.assert_logged_without_secret()

	def refuse(self, *args, json=None, **kwargs) -> requests.Response:
		# A Frappe-format refusal whose message and exception both echo the request.
		echoed = f"Invalid secret {json}"
		response = requests.Response()
		response.status_code = 417
		response._content = frappe.as_json(
			{
				"exception": f"frappe.exceptions.ValidationError: {echoed}",
				"_server_messages": frappe.as_json([frappe.as_json({"message": echoed})]),
			}
		).encode()
		return response

	def test_a_grove_refusal_echoing_the_secret_raises_and_logs_no_secret(self):
		grove = GroveClient("https://grove.example.test", "key", "secret")
		frappe.clear_messages()
		with (
			patch("central.integrations.grove.requests.post", side_effect=self.refuse),
			self.assertRaises(frappe.ValidationError) as raised,
		):
			grove.set_report_secret(SECRET)

		self.assertIn("Invalid secret", str(raised.exception))
		self.assertNotIn(SECRET, str(raised.exception))
		self.assertNotIn(SECRET, frappe.as_json(frappe.local.message_log))
		for log in self.logs():
			self.assertNotIn(SECRET, f"{log.method} {log.error}")

	def test_a_cargo_500_echoing_the_secret_logs_no_secret(self):
		region = frappe.get_doc(
			{
				"doctype": "Region",
				"region": frappe.generate_hash(length=8),
				"atlas_region_id": "7",
				"cargo_base_url": "http://cargo.example.test:8000",
				"status": "Active",
				"cargo_status": "Registered",
				"cargo_webhook_secret": "webhook-secret",
			}
		).insert()
		with (
			patch("central.integrations.cargo.mint_cargo_token", return_value="cargo-token"),
			patch("central.integrations.cargo.requests.post", side_effect=self.echo),
			patch("central.integrations.report_secret.get_report_secret", return_value=SECRET),
		):
			send_to_cargo(region.name)

		self.assert_logged_without_secret()
