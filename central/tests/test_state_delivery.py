import base64
import hashlib
import hmac
import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.central.doctype.asset.asset import Asset
from central.central.doctype.pilot_credential.pilot_credential import PilotCredential
from central.integrations.state_delivery import accept, apply_report

SECRET = "delivery-test-secret"


class TestStateDelivery(IntegrationTestCase):
	"""One region reports what it sees. Central takes the report only from a delivery it
	can authenticate, and only when the report says something new."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		self.enterContext(patch.object(Asset, "ensure_subscription_enabled"))
		self.enterContext(patch.object(Asset, "disable_active_subscription"))
		self.team = frappe.get_doc(
			{"doctype": "Team", "team_name": "Delivery", "owner_user": "Administrator"}
		).insert()
		region = frappe.get_doc(
			{"doctype": "Region", "region": "delivery-" + frappe.generate_hash(length=8)}
		).insert()
		self.cluster = frappe.get_doc(
			{
				"doctype": "Atlas Instance",
				"region": region.name,
				"base_url": "https://atlas.example.test",
				"status": "Active",
			}
		)
		self.cluster.webhook_secret = SECRET
		self.cluster.insert()
		self.server = frappe.get_doc(
			{
				"doctype": "Asset",
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
		return accept(
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
		apply_report(self.cluster.name, report)

	# — Authentication

	def test_a_wrong_signature_is_refused(self):
		with self.assertRaises(frappe.PermissionError):
			self.deliver(self.state_report(), secret="not-the-secret")

	def test_a_missing_header_is_refused(self):
		with self.assertRaises(frappe.PermissionError):
			accept(raw_body=b"{}", region=self.cluster.name, signature=None)
		with self.assertRaises(frappe.PermissionError):
			accept(raw_body=b"{}", region=None, signature="signature")

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

	def test_a_repeated_delivery_is_ignored(self):
		"""Frappe retries a failed delivery, so the same report can arrive twice. The
		second one carries a state Central already recorded, which is the dedupe."""
		report = self.state_report()
		self.deliver(report)
		self.apply(report)

		self.assertEqual(self.deliver(report), {"queued": False, "ignored": "no change"})
		self.assertEqual(self.server.reload().status, "Running")

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
		neighbour = frappe.get_doc(
			{"doctype": "Region", "region": "delivery-" + frappe.generate_hash(length=8)}
		).insert()
		other_cluster = frappe.get_doc(
			{
				"doctype": "Atlas Instance",
				"region": neighbour.name,
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

	# — A deleted server

	def test_a_deleted_server_is_recorded_and_its_credential_revoked(self):
		PilotCredential.mint(
			team=self.team.name, pilot_credential_id="pcred-" + self.server.name, asset=self.server.name
		)
		report = {"event": "vm.gone", "virtual_machine": "vm-00007"}

		self.assertEqual(self.deliver(report), {"queued": True, "resource_id": self.server.name})
		self.apply(report)
		self.assertEqual(self.server.reload().status, "Terminated")
		self.assertEqual(
			frappe.db.get_value("Pilot Credential", "pcred-" + self.server.name, "status"), "Revoked"
		)

	def test_a_delete_report_for_a_dead_server_is_ignored(self):
		self.server.db_set("status", "Terminated")

		self.assertEqual(
			self.deliver({"event": "vm.gone", "virtual_machine": "vm-00007"}),
			{"queued": False, "ignored": "already terminated"},
		)

	# — The action waiting on the report

	def test_the_waiting_action_succeeds_on_its_goal_state(self):
		action = self._action("start")

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
				"asset": self.server.name,
				"remote_vm_id": self.server.atlas_vm_id,
				"requested_by": "Administrator",
				"correlation_id": frappe.generate_hash(length=32),
				"status": "Sent",
			}
		).insert(ignore_permissions=True)
		return action.name
