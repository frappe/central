from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.tests.utils import make_plan
from central.tests.test_iam import ensure_user
from central.tests.utils import ensure_atlas_instance


class TestVirtualMachine(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = ensure_user("server.owner@example.test")
		self.team = frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": "VM Team",
				"owner_user": self.owner,
				"members": [{"user": self.owner, "role": "Owner", "status": "Active"}],
			}
		).insert()
		self.cluster = "blr-server"
		ensure_atlas_instance(self.cluster)

	def test_server_named_by_resource_id_and_links(self):
		server = frappe.get_doc(
			{
				"doctype": "Virtual Machine",
				"resource_id": "vm-xyz",
				"team": self.team.name,
				"cluster": self.cluster,
				"status": "Running",
				"gateway_url": "http://localhost:3030",
			}
		).insert()
		self.assertEqual(server.name, "vm-xyz")
		self.assertEqual(server.team, self.team.name)
		self.assertEqual(server.cluster, self.cluster)

	def test_operator_can_queue_route_removal_for_a_terminated_server(self):
		server = self._server("vm-routes-gone", "Terminated")

		with patch("frappe.enqueue") as enqueue:
			server.remove_routes()

		enqueue.assert_called_once()
		self.assertEqual(enqueue.call_args.kwargs["server"], server.name)

	def test_route_removal_is_refused_for_a_live_server(self):
		server = self._server("vm-routes-live", "Running")

		with patch("frappe.enqueue") as enqueue, self.assertRaises(frappe.ValidationError):
			server.remove_routes()

		enqueue.assert_not_called()

	def test_a_team_member_cannot_queue_route_removal(self):
		server = self._server("vm-routes-member", "Terminated")

		frappe.set_user(self.owner)
		try:
			with patch("frappe.enqueue") as enqueue, self.assertRaises(frappe.PermissionError):
				server.remove_routes()
		finally:
			frappe.set_user("Administrator")

		enqueue.assert_not_called()

	def test_failed_and_terminated_states_queue_notifications(self):
		server = self._server("vm-state-events", "Pending")

		with (
			patch.object(server, "sync_subscription_on_status_change"),
			patch("central.notification.engine.queue_event") as queue_event,
			patch.object(server, "enqueue_route_removal"),
		):
			server.status = "Failed"
			server.save()
			server.status = "Terminated"
			server.save()

		self.assertEqual(
			[call.args[1] for call in queue_event.call_args_list],
			["server_failed", "server_terminated"],
		)

	def _server(self, resource_id: str, status: str):
		return frappe.get_doc(
			{
				"doctype": "Virtual Machine",
				"resource_id": resource_id,
				"team": self.team.name,
				"cluster": self.cluster,
				"status": status,
			}
		).insert()


class TestVirtualMachineSubscriptionSync(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = ensure_user("server.sub.owner@example.test")
		self.team = (
			frappe.get_doc(
				{
					"doctype": "Team",
					"team_name": "VM Sub Team",
					"owner_user": self.owner,
					"members": [{"user": self.owner, "role": "Owner", "status": "Active"}],
				}
			)
			.insert()
			.name
		)
		self.cluster = "blr-server-sub"
		ensure_atlas_instance(self.cluster)
		self.plan_a = make_plan("plan-server-sub-a")
		self.plan_b = make_plan("plan-server-sub-b")
		self._assets = []

	def tearDown(self):
		for resource_id in self._assets:
			for change in frappe.get_all(
				"Subscription Change",
				filters={
					"subscription": [
						"in",
						frappe.get_all(
							"Subscription",
							filters={"team": self.team, "server_id": resource_id},
							pluck="name",
						),
					]
				},
				pluck="name",
			):
				frappe.delete_doc("Subscription Change", change, force=True)
			for sub in frappe.get_all(
				"Subscription", filters={"team": self.team, "server_id": resource_id}, pluck="name"
			):
				frappe.delete_doc("Subscription", sub, force=True)
			frappe.delete_doc("Virtual Machine", resource_id, force=True)

	def _make_server(self, resource_id, status="Pending", plan=None):
		self._assets.append(resource_id)
		return frappe.get_doc(
			{
				"doctype": "Virtual Machine",
				"resource_id": resource_id,
				"team": self.team,
				"cluster": self.cluster,
				"status": status,
				"plan": plan or self.plan_a,
			}
		).insert()

	def _subscription_for(self, resource_id):
		return frappe.db.get_value("Subscription", {"team": self.team, "server_id": resource_id}, "name")

	def test_running_status_creates_subscription_when_missing(self):
		server = self._make_server("vm-sub-create", status="Pending")
		server.status = "Running"
		server.save()

		sub_name = self._subscription_for(server.name)
		self.assertTrue(sub_name)
		self.assertEqual(frappe.db.get_value("Subscription", sub_name, "enabled"), 1)
		self.assertEqual(frappe.db.get_value("Subscription", sub_name, "plan"), self.plan_a)

	def test_running_status_enables_existing_disabled_subscription(self):
		server = self._make_server("vm-sub-enable", status="Running")
		sub_name = self._subscription_for(server.name)
		frappe.db.set_value("Subscription", sub_name, "enabled", 0)

		# Cycle status away and back to Running to re-trigger the sync.
		server.reload()
		server.status = "Stopped"
		server.save()
		server.status = "Running"
		server.save()

		self.assertEqual(frappe.db.get_value("Subscription", sub_name, "enabled"), 1)

	def test_terminated_status_disables_active_subscription(self):
		server = self._make_server("vm-sub-terminate", status="Running")
		sub_name = self._subscription_for(server.name)

		server.status = "Terminated"
		server.save()

		self.assertEqual(frappe.db.get_value("Subscription", sub_name, "enabled"), 0)

	def test_plan_change_while_running_updates_subscription_plan(self):
		server = self._make_server("vm-sub-plan", status="Running", plan=self.plan_a)
		sub_name = self._subscription_for(server.name)

		server.plan = self.plan_b
		server.save()

		self.assertEqual(frappe.db.get_value("Subscription", sub_name, "plan"), self.plan_b)
		changes = frappe.get_all(
			"Subscription Change",
			filters={"subscription": sub_name, "change_type": "Plan Changed"},
			fields=["old_value", "new_value"],
		)
		self.assertEqual(len(changes), 1)
		self.assertEqual(changes[0].old_value, self.plan_a)
		self.assertEqual(changes[0].new_value, self.plan_b)
