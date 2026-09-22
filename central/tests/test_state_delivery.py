import base64
import hashlib
import hmac
import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils.password import remove_encrypted_password

from central.api.state_delivery import REGION_HEADER, SOURCE_HEADER, receive
from central.infrastructure.doctype.virtual_machine.virtual_machine import VirtualMachine
from central.integrations.state_delivery import (
	accept_atlas_report,
	accept_cargo_report,
	apply_atlas_report,
)

SECRET = "delivery-test-secret"


class TestStateDelivery(IntegrationTestCase):
	"""One region reports what it sees. Central takes the report only from a delivery it
	can authenticate, and only when the report says something new."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		self.enterContext(patch.object(VirtualMachine, "ensure_subscription_enabled"))
		self.enterContext(patch.object(VirtualMachine, "disable_active_subscription"))
		self.team = frappe.get_doc(
			{"doctype": "Team", "team_name": "Delivery", "owner_user": "Administrator"}
		).insert()
		self.cluster = frappe.get_doc(
			{
				"doctype": "Region",
				"region": "delivery-" + frappe.generate_hash(length=8),
				"base_url": "https://atlas.example.test",
				"status": "Active",
			}
		)
		self.cluster.webhook_secret = SECRET
		self.cluster.insert()
		self.server = frappe.get_doc(
			{
				"doctype": "Virtual Machine",
				"resource_id": "server-" + frappe.generate_hash(length=8),
				"team": self.team.name,
				"cluster": self.cluster.name,
				"atlas_vm_id": "vm-00007",
				"status": "Stopped",
			}
		).insert()
		self.queued = self.enterContext(patch("central.integrations.state_delivery.frappe.enqueue"))

	# — Helpers

	def deliver(self, report: dict, *, secret: str = SECRET, region: str | None = None) -> dict:
		"""Sign a report the way Frappe's Webhook does, then hand it to the receiver."""
		body = json.dumps(report).encode()
		signature = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
		return accept_atlas_report(
			raw_body=body,
			region=self.cluster.name if region is None else region,
			signature=signature,
		)

	def state_report(self, status: str = "running", **overrides) -> dict:
		report = {
			"event": "vm.state",
			"virtual_machine": "vm-00007",
			"status": status,
			"observed_at": str(frappe.utils.now_datetime()),
		}
		report.update(overrides)
		return report

	def apply(self, report: dict) -> None:
		apply_atlas_report(self.cluster.name, report)

	# — Authentication

	def test_a_wrong_signature_is_refused(self):
		with self.assertRaises(frappe.PermissionError):
			self.deliver(self.state_report(), secret="not-the-secret")

	def test_a_missing_header_is_refused(self):
		with self.assertRaises(frappe.PermissionError):
			accept_atlas_report(raw_body=b"{}", region=self.cluster.name, signature=None)
		with self.assertRaises(frappe.PermissionError):
			accept_atlas_report(raw_body=b"{}", region=None, signature="signature")

	def test_an_unknown_region_is_refused(self):
		with self.assertRaises(frappe.PermissionError):
			self.deliver(self.state_report(), region="no-such-region")

	def test_a_disabled_region_is_refused(self):
		self.cluster.db_set("status", "Disabled")
		with self.assertRaises(frappe.PermissionError):
			self.deliver(self.state_report())

	def test_a_region_without_a_secret_is_refused(self):
		self.cluster.webhook_secret = None
		self.cluster.save()
		with self.assertRaises(frappe.PermissionError):
			self.deliver(self.state_report())

	def test_a_refusal_never_says_which_check_failed(self):
		with self.assertRaises(frappe.PermissionError) as wrong_secret:
			self.deliver(self.state_report(), secret="not-the-secret")
		with self.assertRaises(frappe.PermissionError) as unknown_region:
			self.deliver(self.state_report(), region="no-such-region")
		self.assertEqual(str(wrong_secret.exception), str(unknown_region.exception))

	# — What Central does with an authenticated report

	def test_a_new_state_is_queued_and_applied(self):
		report = self.state_report()
		self.assertEqual(self.deliver(report), {"queued": True, "resource_id": self.server.name})
		self.queued.assert_called_once()

		self.apply(report)
		self.assertEqual(self.server.reload().status, "Running")
		self.queued.assert_any_call(
			"central.integrations.servers.refresh_server",
			name=self.server.name,
			enqueue_after_commit=True,
			job_id=f"server-refresh:{self.server.name}",
			deduplicate=True,
		)

	def test_a_repeated_delivery_is_ignored(self):
		"""Frappe retries a failed delivery, so the same report can arrive twice. The
		second one carries a state Central already recorded, which is the dedupe."""
		report = self.state_report()
		self.deliver(report)
		self.apply(report)

		self.assertEqual(self.deliver(report), {"queued": False, "ignored": "no change"})
		self.assertEqual(self.server.reload().status, "Running")

	def test_a_report_older_than_the_last_is_dropped(self):
		"""An older observed_at is a reorder or replay and must not overwrite a newer state."""
		self.apply(self.state_report(status="running", observed_at="2026-06-02 00:00:00"))
		self.assertEqual(self.server.reload().status, "Running")

		self.apply(self.state_report(status="stopped", observed_at="2026-06-01 00:00:00"))
		self.assertEqual(self.server.reload().status, "Running")

	def test_a_newer_report_overwrites_an_earlier_one(self):
		"""A newer observed_at is applied, so a genuine later change still lands."""
		self.apply(self.state_report(status="running", observed_at="2026-06-01 00:00:00"))
		self.assertEqual(self.server.reload().status, "Running")

		self.apply(self.state_report(status="stopped", observed_at="2026-06-02 00:00:00"))
		self.assertEqual(self.server.reload().status, "Stopped")

	def test_an_unchanged_state_is_ignored(self):
		self.server.db_set("status", "Running")

		self.assertEqual(self.deliver(self.state_report()), {"queued": False, "ignored": "no change"})
		self.queued.assert_not_called()

	def test_the_recorded_time_is_Central_own_clock(self):
		"""A report carries the region's clock and a scoped read carries Central's, so
		ordering by the report would let skew between them suppress events."""
		behind = str(frappe.utils.add_to_date(frappe.utils.now_datetime(), days=-1))

		self.apply(self.state_report(observed_at=behind))
		self.server.reload()
		self.assertEqual(self.server.status, "Running")
		self.assertGreater(
			frappe.utils.get_datetime(self.server.state_observed_at), frappe.utils.get_datetime(behind)
		)

	def test_one_region_cannot_report_on_another_region_server(self):
		"""A VM id is only unique inside its region, so a signed report from the wrong
		region must not reach a server of the same id somewhere else."""
		other_cluster = frappe.get_doc(
			{
				"doctype": "Region",
				"region": "delivery-" + frappe.generate_hash(length=8),
				"base_url": "https://atlas.neighbour.test",
				"status": "Active",
			}
		)
		other_cluster.webhook_secret = SECRET
		other_cluster.insert()

		reply = self.deliver(self.state_report(status="stopped"), region=other_cluster.name)
		self.assertEqual(reply, {"queued": False, "ignored": "unknown server"})
		self.assertEqual(self.server.reload().status, "Stopped")

	def test_an_unknown_server_is_ignored(self):
		report = self.state_report(virtual_machine="vm-99999")

		self.assertEqual(self.deliver(report), {"queued": False, "ignored": "unknown server"})

	def test_an_unsupported_event_or_status_is_ignored(self):
		self.assertEqual(
			self.deliver(self.state_report(event="vm.resized")),
			{"queued": False, "ignored": "unsupported event 'vm.resized'"},
		)
		self.assertEqual(
			self.deliver(self.state_report(status="melting")),
			{"queued": False, "ignored": "unsupported status 'melting'"},
		)

	def test_a_body_that_is_not_an_object_is_ignored(self):
		self.assertEqual(self.deliver(["vm-00007"]), {"queued": False, "ignored": "unreadable body"})

	# — The action waiting on the report

	def test_the_waiting_action_succeeds_on_its_goal_state(self):
		action = self._action("start")

		self.apply(self.state_report())
		self.assertEqual(frappe.db.get_value("Resource Action", action, "status"), "Succeeded")

	def test_a_restart_waits_to_see_the_server_leave_running(self):
		"""A restart begins and ends at Running, so the goal state alone proves nothing.
		It succeeds only after the region reports the server away from Running."""
		action = self._action("restart")
		self.server.db_set("status", "Running")

		self.apply(self.state_report())
		self.assertEqual(frappe.db.get_value("Resource Action", action, "status"), "Sent")

		self.apply(self.state_report(status="stopped"))
		self.assertEqual(frappe.db.get_value("Resource Action", action, "status"), "In Progress")

		self.apply(self.state_report())
		self.assertEqual(frappe.db.get_value("Resource Action", action, "status"), "Succeeded")

	def test_the_waiting_action_is_left_alone_on_any_other_state(self):
		action = self._action("stop")

		self.apply(self.state_report())
		self.assertEqual(frappe.db.get_value("Resource Action", action, "status"), "Sent")

	def _action(self, verb: str) -> str:
		"""A dispatched action waiting for this server to reach its goal state."""
		action = frappe.get_doc(
			{
				"doctype": "Resource Action",
				"resource_type": "Server",
				"action": verb,
				"team": self.team.name,
				"atlas_instance": self.cluster.name,
				"resource_id": self.server.name,
				"server": self.server.name,
				"remote_vm_id": self.server.atlas_vm_id,
				"requested_by": "Administrator",
				"correlation_id": frappe.generate_hash(length=32),
				"status": "Sent",
			}
		).insert(ignore_permissions=True)
		return action.name


class TestDeliveryRouting(IntegrationTestCase):
	"""One endpoint serves every plane, so the source header picks the handler."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.accepted = self.enterContext(
			patch("central.api.state_delivery.state_delivery.accept_atlas_report")
		)
		self.accepted_cargo = self.enterContext(
			patch("central.api.state_delivery.state_delivery.accept_cargo_report")
		)
		frappe.local.request = SimpleNamespace(get_data=lambda: b"{}")
		self.addCleanup(delattr, frappe.local, "request")

	def deliver(self, source: str | None) -> dict:
		headers = {SOURCE_HEADER: source, REGION_HEADER: "region", "X-Frappe-Webhook-Signature": "s"}
		with patch("central.api.state_delivery.frappe.get_request_header", headers.get):
			return receive()

	def test_an_atlas_delivery_reaches_the_state_handler(self):
		self.deliver("atlas")

		self.assertTrue(self.accepted.called)

	def test_the_header_is_read_whatever_its_case(self):
		self.deliver("Atlas")

		self.assertTrue(self.accepted.called)

	def test_a_cargo_delivery_reaches_the_service_handler(self):
		self.deliver("cargo")

		self.assertTrue(self.accepted_cargo.called)
		self.assertFalse(self.accepted.called)

	def test_a_delivery_that_names_no_sender_is_refused(self):
		with self.assertRaises(frappe.PermissionError):
			self.deliver(None)

		self.assertFalse(self.accepted.called)

	def test_an_unknown_sender_is_refused(self):
		with self.assertRaises(frappe.PermissionError):
			self.deliver("pilot")

		self.assertFalse(self.accepted.called)


class TestCargoServiceDelivery(IntegrationTestCase):
	"""A region reports what it serves. Central records it only from a delivery its own
	Cargo secret signed, and only for a service and a state Central knows."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		self.region = frappe.get_doc(
			{
				"doctype": "Region",
				"region": "service-" + frappe.generate_hash(length=8),
				"cargo_base_url": "https://cargo.example.test",
				"cargo_status": "Registered",
			}
		)
		self.region.cargo_webhook_secret = SECRET
		self.region.insert()

	# — Helpers

	def deliver(self, report: dict, *, secret: str = SECRET, region: str | None = None) -> dict:
		body = json.dumps(report).encode()
		signature = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
		return accept_cargo_report(
			raw_body=body,
			region=self.region.name if region is None else region,
			signature=signature,
		)

	def service_report(self, **overrides) -> dict:
		report = {
			"region": self.region.name,
			"service": "storage",
			"status": "Available",
			"service_endpoint": "https://s3-svc.example.test",
		}
		report.update(overrides)
		return report

	def detail(self, service: str = "storage"):
		return frappe.get_doc("Service Detail", f"{self.region.name}-{service}")

	# — Authentication

	def test_a_wrong_signature_is_refused(self):
		with self.assertRaises(frappe.PermissionError):
			self.deliver(self.service_report(), secret="not-the-secret")

	def test_a_missing_header_is_refused(self):
		with self.assertRaises(frappe.PermissionError):
			self.deliver(self.service_report(), region="")

	def test_an_unregistered_region_is_refused(self):
		self.region.db_set("cargo_status", "Draft")

		with self.assertRaises(frappe.PermissionError):
			self.deliver(self.service_report())

	def test_a_region_without_a_secret_is_refused(self):
		remove_encrypted_password("Region", self.region.name, "cargo_webhook_secret")
		frappe.clear_document_cache("Region", self.region.name)

		with self.assertRaises(frappe.PermissionError):
			self.deliver(self.service_report())

	def test_one_region_cannot_report_for_another(self):
		other = frappe.get_doc(
			{"doctype": "Region", "region": "other-" + frappe.generate_hash(length=8)}
		).insert()

		with self.assertRaises(frappe.PermissionError):
			self.deliver(self.service_report(), region=other.name)

	# — What Central records

	def test_a_reported_service_is_recorded_against_its_region(self):
		self.deliver(self.service_report())
		detail = self.detail()

		self.assertEqual(detail.region, self.region.name)
		self.assertEqual(detail.service, "storage")
		self.assertEqual(detail.status, "Available")
		self.assertEqual(detail.service_endpoint, "https://s3-svc.example.test")

	def test_each_service_of_a_region_gets_its_own_row(self):
		self.deliver(self.service_report())
		self.deliver(self.service_report(service="telemetry"))

		self.assertEqual(self.detail("storage").service, "storage")
		self.assertEqual(self.detail("telemetry").service, "telemetry")

	def test_reporting_again_rewrites_the_same_row(self):
		self.deliver(self.service_report())
		self.deliver(self.service_report(status="Not Available", service_endpoint=None))
		detail = self.detail()

		self.assertEqual(detail.status, "Not Available")
		self.assertEqual(frappe.db.count("Service Detail", {"region": self.region.name}), 1)

	def test_the_activation_time_is_the_first_one_reported(self):
		self.deliver(self.service_report())
		activated = self.detail().activated_on

		self.deliver(self.service_report())

		self.assertEqual(self.detail().activated_on, activated)

	def test_coming_back_after_an_outage_is_a_new_activation(self):
		self.deliver(self.service_report())
		activated = self.detail().activated_on
		self.deliver(self.service_report(status="Not Available"))

		self.deliver(self.service_report())

		self.assertGreaterEqual(self.detail().activated_on, activated)
		self.assertEqual(self.detail().status, "Available")

	# — What Central refuses to record

	def test_an_unknown_service_is_ignored(self):
		reply = self.deliver(self.service_report(service="database"))

		self.assertIn("unsupported service", reply["ignored"])
		self.assertFalse(frappe.db.exists("Service Detail", {"region": self.region.name}))

	def test_an_unknown_status_is_ignored(self):
		reply = self.deliver(self.service_report(status="Active"))

		self.assertIn("unsupported status", reply["ignored"])
		self.assertFalse(frappe.db.exists("Service Detail", {"region": self.region.name}))

	def test_a_body_that_is_not_an_object_is_ignored(self):
		body = b"[]"
		signature = base64.b64encode(hmac.new(SECRET.encode(), body, hashlib.sha256).digest()).decode()

		reply = accept_cargo_report(raw_body=body, region=self.region.name, signature=signature)

		self.assertEqual(reply["ignored"], "unreadable body")
