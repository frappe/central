# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Resize a composed config: changed-event re-lock at current rates (#82)."""

from unittest.mock import patch

import frappe
from frappe.utils import get_first_day, get_last_day, nowdate

from central.billing.api.admin.catalog import update_component_rate
from central.billing.catalog import subscriptions
from central.billing.catalog.pricing import set_catalog_rate
from central.billing.revenue.invoicing import generate_team_invoice
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	complete_billing_profile,
	ensure_atlas_instance,
	ensure_team,
	make_plan,
	run_enqueued_inline,
	set_team_tier,
)
from central.errors import AtlasConnectionError
from central.integrations.server_provisioning import _process_locked

TEAM = "team-resize"
CLUSTER = "ap-south-1"
SMALL = [
	{"resource_type": "Compute", "quantity": 2, "unit": "vCPU"},
	{"resource_type": "Memory", "quantity": 8, "unit": "GB"},
	{"resource_type": "Disk", "quantity": 40, "unit": "GB"},
]  # General ratio 4: 2*500 + 8*250 + 40*10 = 3400
BIG = [
	{"resource_type": "Compute", "quantity": 4, "unit": "vCPU"},
	{"resource_type": "Memory", "quantity": 16, "unit": "GB"},
	{"resource_type": "Disk", "quantity": 40, "unit": "GB"},
]  # General ratio 4: 4*500 + 16*250 + 40*10 = 6400 (at base card)


def _ensure_tier_level(name):
	"""A linkable Trust Tier Level so set_team_tier's pin resolves. Money caps come
	from set_team_tier's override, so the threshold here is just a placeholder."""
	if not frappe.db.exists("Trust Tier Level", name):
		frappe.get_doc(
			{
				"doctype": "Trust Tier Level",
				"__newname": name,
				"tier": name,
				"sequence": 1,
				"is_default": 0,
				"max_resource_count": 50,
				"min_paid_invoices": 0,
				"thresholds": [{"currency": "INR", "max_spend": 100000, "min_cumulative_paid": 0}],
			}
		).insert(ignore_permissions=True)


class TestResizeComposed(IntegrationTestCase):
	def setUp(self):
		ensure_atlas_instance(CLUSTER)
		ensure_team(TEAM)
		complete_billing_profile(TEAM, currency="INR")
		_ensure_tier_level("t1")
		set_team_tier(TEAM, max_spend=1_000_000)
		for resource_type, rate in (("Compute", 500), ("Memory", 250), ("Disk", 10)):
			set_catalog_rate("Resource Type", resource_type, "INR", rate)
		for name in frappe.get_all("Subscription", filters={"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": name})
			frappe.delete_doc("Subscription", name, force=True)
		frappe.db.delete("Invoice", {"team": TEAM})

		def record_resize(server, shape):
			frappe.db.set_value("Virtual Machine", server.name, shape)

		self.resize_server = self.enterContext(
			patch("central.integrations.servers.resize_server", side_effect=record_resize)
		)

	def _ready(self, sub):
		"""Mark a subscription's VM Stopped — the state a resize requires (Firecracker
		can't reconfigure a running machine). Returns the server id."""
		server = frappe.db.get_value("Subscription", sub, "server_id")
		frappe.db.set_value("Virtual Machine", server, {"status": "Stopped", "atlas_vm_id": "vm-resize-test"})
		return server

	def _segments(self, sub):
		return frappe.get_all(
			"Subscription Change",
			filters={"subscription": sub, "change_type": ["in", ["Created", "Plan Changed"]]},
			fields=["change_type", "locked_rate", "new_value"],
			order_by="effective_at asc, creation asc",
		)

	def _provision(self, includes=None, start_date=None):
		return subscriptions.provision_composed_subscription(
			TEAM, CLUSTER, includes or SMALL, "General", start_date=start_date
		)["subscription"]

	def test_preset_plus_disk_rate_adds_only_the_extra_disk(self):
		"""Growing a preset's disk keeps the bundle price and adds the disk rate for the GB
		beyond the plan's own disk, instead of dropping to the cheaper a-la-carte total."""
		plan = make_plan(
			"resize-preset-rate",
			rates=[{"cluster": "", "currency": "INR", "rate": 5000}],
			includes=[
				{"resource_type": "Compute", "quantity": 2, "unit": "vCPU"},
				{"resource_type": "Memory", "quantity": 8, "unit": "GB"},
				{"resource_type": "Disk", "quantity": 40, "unit": "GB"},
			],
			sub_category="General",
		)
		sub = subscriptions.provision_subscription(TEAM, CLUSTER, plan)["subscription"]
		doc = frappe.get_doc("Subscription", sub)

		# 5000 bundle + (80 - 40) GB * 10/GB = 5400 (the a-la-carte total would be only 3800).
		self.assertEqual(subscriptions._preset_plus_disk_rate(doc, plan, 80), 5400)
		# No growth beyond the plan's own disk keeps the plain bundle price.
		self.assertEqual(subscriptions._preset_plus_disk_rate(doc, plan, 40), 5000)

	def test_resize_relocks_at_current_rates_old_row_untouched(self):
		sub = self._provision()
		self._ready(sub)
		frappe.set_user("Administrator")
		update_component_rate("Compute", "INR", 900)  # rate card moves
		subscriptions.resize_composed_subscription(sub, BIG, "General")

		segments = self._segments(sub)
		self.assertEqual(len(segments), 2)
		# Old segment keeps its locked rate (grandfathered, unaltered).
		self.assertEqual(segments[0].change_type, "Created")
		self.assertEqual(segments[0].locked_rate, 3400)
		# New segment is re-resolved at the CURRENT card: 4*900 + 16*250 + 40*10 = 8000.
		self.assertEqual(segments[1].change_type, "Plan Changed")
		self.assertEqual(segments[1].locked_rate, 8000)
		self.assertEqual(segments[1].new_value, "Custom: 4 vCPU · 16 GB RAM · 40 GB disk")

	def test_resize_invoice_has_two_prorated_segments(self):
		start = get_first_day(nowdate())
		sub = self._provision(start_date=str(start))
		# Author the resize re-lock as a mid-month Plan Changed segment so proration has
		# two spans regardless of the day the suite runs — resize stamps now_datetime(),
		# which collapses onto the opening segment when today is the 1st (segment authoring
		# itself is covered by test_resize_relocks…). Bills Created [1..15] + resize [15..].
		mid = frappe.utils.add_days(start, 14)
		frappe.get_doc(
			{
				"doctype": "Subscription Change",
				"subscription": sub,
				"change_type": "Plan Changed",
				"new_value": "Custom: 4 vCPU · 16 GB RAM · 40 GB disk",
				"locked_rate": 6400,
				"currency": "INR",
				"effective_at": f"{mid} 00:00:00",
			}
		).insert(ignore_permissions=True)
		invoice = generate_team_invoice(TEAM, str(start), str(get_last_day(nowdate())))
		doc = frappe.get_doc("Invoice", invoice)
		self.assertEqual(len(doc.items), 2)
		self.assertEqual({line.rate for line in doc.items}, {3400, 6400})

	def test_resize_to_identical_composition_is_noop(self):
		sub = self._provision()
		subscriptions.resize_composed_subscription(sub, SMALL, "General")
		# Only the opening Created segment — no Plan Changed event.
		self.assertEqual(len(self._segments(sub)), 1)

	def test_off_ratio_resize_rejected(self):
		sub = self._provision()
		bad = [
			{"resource_type": "Compute", "quantity": 4, "unit": "vCPU"},
			{"resource_type": "Memory", "quantity": 8, "unit": "GB"},  # General needs 16
			{"resource_type": "Disk", "quantity": 40, "unit": "GB"},
		]
		with self.assertRaises(frappe.ValidationError):
			subscriptions.resize_composed_subscription(sub, bad, "General")
		self.assertEqual(len(self._segments(sub)), 1)  # nothing appended

	def test_over_headroom_resize_rejected(self):
		sub = self._provision()
		set_team_tier(TEAM, max_spend=4000)  # cap below the BIG config (6400)
		with self.assertRaises(frappe.ValidationError):
			subscriptions.resize_composed_subscription(sub, BIG, "General")
		self.assertEqual(len(self._segments(sub)), 1)

	def test_over_headroom_preset_resize_rejected(self):
		# Parity with the composed guard above: a preset target must hit the cap too, so a
		# resize onto a pricier bundle can't slip past trust-tier headroom.
		sub = self._provision()
		self._ready(sub)
		set_team_tier(TEAM, max_spend=4000)
		plan = make_plan("over-headroom", rates=[{"cluster": "", "currency": "INR", "rate": 5000}])
		with self.assertRaises(frappe.ValidationError):
			subscriptions.resize_to_plan(sub, plan)
		self.assertEqual(len(self._segments(sub)), 1)  # no new segment opened

	def test_resize_records_nothing_on_cancelled(self):
		sub = self._provision()
		subscriptions.cancel_subscription(sub)
		result = subscriptions.resize_composed_subscription(sub, BIG, "General")
		self.assertIsNone(result)
		self.assertEqual(len(self._segments(sub)), 1)

	def test_resize_records_nothing_on_terminated(self):
		sub = self._provision()
		server = frappe.db.get_value("Subscription", sub, "server_id")
		frappe.db.set_value("Virtual Machine", server, "status", "Terminated")
		result = subscriptions.resize_composed_subscription(sub, BIG, "General")
		self.assertIsNone(result)
		self.assertEqual(len(self._segments(sub)), 1)

	def test_composed_resize_relocks_running_subscription(self):
		sub = self._provision()
		server = frappe.db.get_value("Subscription", sub, "server_id")
		frappe.db.set_value("Virtual Machine", server, "status", "Running")
		subscriptions.resize_composed_subscription(sub, BIG, "General")
		self.assertEqual(len(self._segments(sub)), 2)  # re-priced

	def test_resize_rejects_disk_shrink_without_touching_vm(self):
		sub = self._provision()  # SMALL — 40 GB disk
		server = self._ready(sub)
		frappe.db.set_value("Virtual Machine", server, "disk_gigabytes", 100)  # server grew to 100 GB
		with self.assertRaisesRegex(frappe.ValidationError, "Disk can't shrink"):
			subscriptions.begin_resize(sub, includes=BIG, sub_category="General")  # BIG is 40 GB < 100
		self.assertEqual(len(self._segments(sub)), 1)  # no re-price

	def test_resize_to_preset_plan_relocks(self):
		sub = self._provision()
		self._ready(sub)
		plan = make_plan("resize-target", rates=[{"cluster": "", "currency": "INR", "rate": 1500}])
		subscriptions.resize_to_plan(sub, plan)
		doc = frappe.get_doc("Subscription", sub)
		self.assertEqual((doc.pricing_mode, doc.plan), ("Preset", plan))
		self.assertEqual(self._segments(sub)[-1].locked_rate, 1500)

	def test_slide_off_preset_opens_composed_segment(self):
		plan = make_plan("preset-slide", rates=[{"cluster": "", "currency": "INR", "rate": 1500}])
		sub = subscriptions.create_subscription(TEAM, CLUSTER, plan=plan).name
		self._ready(sub)
		subscriptions.resize_composed_subscription(sub, SMALL, "General")
		doc = frappe.get_doc("Subscription", sub)
		self.assertEqual(doc.pricing_mode, "Composed")
		self.assertIsNone(doc.plan)
		segments = self._segments(sub)
		self.assertEqual(len(segments), 2)
		self.assertEqual(segments[0].locked_rate, 1500)  # preset segment closed
		self.assertEqual(segments[1].locked_rate, 3400)  # composed (no bundle discount)

	def test_pick_preset_from_composed_drops_composition(self):
		sub = self._provision()
		plan = make_plan("preset-pick", rates=[{"cluster": "", "currency": "INR", "rate": 1500}])
		subscriptions.change_plan(sub, plan)
		doc = frappe.get_doc("Subscription", sub)
		self.assertEqual(doc.pricing_mode, "Preset")
		self.assertEqual(doc.plan, plan)
		self.assertEqual(len(doc.includes), 0)
		segments = self._segments(sub)
		self.assertEqual(segments[-1].locked_rate, 1500)

	# --- begin_resize: the async front door (#84) --------------------------------

	def test_begin_resize_creates_a_durable_action(self):
		sub = self._provision()
		server = self._ready(sub)
		with patch("frappe.enqueue") as enqueue:
			result = subscriptions.begin_resize(sub, includes=BIG, sub_category="General")
		self.assertTrue(result["queued"])
		self.assertTrue(result["resized"])
		self.assertEqual(result["status"], "Queued")
		enqueue.assert_called_once()
		self.resize_server.assert_not_called()
		self.assertEqual(
			frappe.db.get_value("Resource Action", result["action"], ["action", "resource_id"]),
			("resize", server),
		)
		self.assertEqual(len(self._segments(sub)), 1)  # billing re-locks only in the job

	def test_begin_resize_job_reshapes_then_relocks(self):
		sub = self._provision()
		self._ready(sub)
		with patch("frappe.enqueue", side_effect=run_enqueued_inline):
			result = subscriptions.begin_resize(sub, includes=BIG, sub_category="General")
		self.resize_server.assert_called_once()
		self.assertEqual(frappe.db.get_value("Resource Action", result["action"], "status"), "Succeeded")
		self.assertEqual(len(self._segments(sub)), 2)  # re-priced once the job landed

	def test_begin_resize_onto_a_preset_with_a_larger_disk(self):
		"""A preset's CPU and memory pass even off the profile ratio, since the preset sells them."""
		sub = self._provision()
		self._ready(sub)
		plan = make_plan(
			"resize-preset-off-ratio",
			rates=[{"cluster": "", "currency": "INR", "rate": 5000}],
			includes=[
				{"resource_type": "Compute", "quantity": 6, "unit": "vCPU"},
				{"resource_type": "Memory", "quantity": 6, "unit": "GB"},
				{"resource_type": "Disk", "quantity": 40, "unit": "GB"},
			],
			sub_category="General",
		)

		with patch("frappe.enqueue", side_effect=run_enqueued_inline):
			subscriptions.begin_resize(sub, plan=plan, disk_gigabytes=80)

		self.resize_server.assert_called_once()
		doc = frappe.get_doc("Subscription", sub)
		self.assertEqual(doc.pricing_mode, "Composed")
		self.assertIsNone(frappe.db.get_value("Virtual Machine", doc.server_id, "plan"))
		self.assertEqual(
			{row.resource_type: row.quantity for row in doc.includes},
			{"Compute": 6, "Memory": 6, "Disk": 80},
		)

	def test_begin_resize_is_a_noop_on_the_same_config(self):
		sub = self._provision()
		self._ready(sub)
		with patch("frappe.enqueue") as enqueue:
			result = subscriptions.begin_resize(sub, includes=SMALL, sub_category="General")
		self.assertEqual(result, {"queued": False, "resized": False})
		enqueue.assert_not_called()

	def test_begin_resize_rejects_disk_shrink_synchronously(self):
		sub = self._provision()  # SMALL — 40 GB disk
		server = self._ready(sub)
		frappe.db.set_value("Virtual Machine", server, "disk_gigabytes", 100)  # server grew to 100 GB
		with patch("frappe.enqueue") as enqueue:
			with self.assertRaisesRegex(frappe.ValidationError, "Disk can't shrink"):
				subscriptions.begin_resize(sub, includes=BIG, sub_category="General")  # BIG is 40 GB
		enqueue.assert_not_called()  # refused before anything is queued
		self.assertFalse(frappe.db.exists("Resource Action", {"resource_id": server}))

	def test_begin_resize_rejects_over_headroom_preset_synchronously(self):
		sub = self._provision()
		server = self._ready(sub)
		set_team_tier(TEAM, max_spend=4000)
		plan = make_plan("over-headroom-sync", rates=[{"cluster": "", "currency": "INR", "rate": 5000}])
		with patch("frappe.enqueue") as enqueue:
			with self.assertRaises(frappe.ValidationError):
				subscriptions.begin_resize(sub, plan=plan)
		enqueue.assert_not_called()  # rejected up front, nothing queued
		self.assertFalse(frappe.db.exists("Resource Action", {"resource_id": server}))

	def test_begin_resize_returns_the_action_already_running(self):
		sub = self._provision()
		self._ready(sub)
		with patch("frappe.enqueue") as enqueue:
			first = subscriptions.begin_resize(sub, includes=BIG, sub_category="General")
			second = subscriptions.begin_resize(sub, includes=BIG, sub_category="General")
		self.assertEqual(second["action"], first["action"])
		self.assertEqual(enqueue.call_count, 1)

	def test_begin_resize_relocks_inline_when_there_is_no_live_vm(self):
		sub = self._provision()  # server defaults to Pending (never started)
		with patch("frappe.enqueue") as enqueue:
			result = subscriptions.begin_resize(sub, includes=BIG, sub_category="General")
		self.assertEqual(result, {"queued": False, "resized": True})
		enqueue.assert_not_called()  # nothing slow to defer
		self.assertEqual(len(self._segments(sub)), 2)  # re-priced inline

	def test_begin_resize_rejects_a_live_server_without_an_atlas_identity(self):
		sub = self._provision()
		server = frappe.db.get_value("Subscription", sub, "server_id")
		frappe.db.set_value("Virtual Machine", server, {"status": "Stopped", "atlas_vm_id": None})

		with self.assertRaisesRegex(frappe.ValidationError, "no verified regional identity"):
			subscriptions.begin_resize(sub, includes=BIG, sub_category="General")

		self.assertFalse(frappe.db.exists("Resource Action", {"resource_id": server}))

	def test_failed_remote_resize_is_recorded_on_the_action(self):
		sub = self._provision()
		self._ready(sub)
		self.resize_server.side_effect = AtlasConnectionError("host unavailable")
		with patch("frappe.enqueue", side_effect=run_enqueued_inline):
			result = subscriptions.begin_resize(sub, includes=BIG, sub_category="General")
		action = frappe.get_doc("Resource Action", result["action"])
		self.assertEqual(action.status, "Uncertain")
		self.assertIn("host unavailable", frappe.db.get_value("Error Log", action.error_log, "error"))
		self.assertEqual(len(self._segments(sub)), 1)  # billing stayed on the old segment

	def test_unconfirmed_remote_shape_does_not_relock_billing(self):
		sub = self._provision()
		self._ready(sub)
		with patch("frappe.enqueue"):
			result = subscriptions.begin_resize(sub, includes=BIG, sub_category="General")

		self.resize_server.side_effect = lambda _server, _shape: None
		_process_locked(result["action"])

		action = frappe.get_doc("Resource Action", result["action"])
		self.assertEqual(action.status, "Uncertain")
		self.assertIn(
			"did not report the requested server size",
			frappe.db.get_value("Error Log", action.error_log, "error"),
		)
		self.assertEqual(len(self._segments(sub)), 1)

	def test_billing_failure_recovers_without_repeating_the_remote_resize(self):
		sub = self._provision()
		server = self._ready(sub)
		with patch("frappe.enqueue"):
			result = subscriptions.begin_resize(sub, includes=BIG, sub_category="General")

		def record_target(_server, shape):
			frappe.db.set_value("Virtual Machine", server, shape)

		self.resize_server.side_effect = record_target
		with patch(
			"central.billing.catalog.subscriptions.apply_resize_billing",
			side_effect=RuntimeError("billing unavailable"),
		):
			_process_locked(result["action"])

		action = frappe.get_doc("Resource Action", result["action"])
		self.assertEqual(action.status, "Sent")
		self.assertIn("billing unavailable", frappe.db.get_value("Error Log", action.error_log, "error"))
		self.assertEqual(len(self._segments(sub)), 1)

		with patch("central.integrations.servers.observe_server"):
			_process_locked(action.name)
		self.assertEqual(frappe.db.get_value("Resource Action", action.name, "status"), "Succeeded")
		self.assertEqual(self.resize_server.call_count, 1)
		self.assertEqual(len(self._segments(sub)), 2)

	def test_recovery_observes_before_repeating_a_dispatched_resize(self):
		sub = self._provision()
		server = self._ready(sub)
		with patch("frappe.enqueue"):
			result = subscriptions.begin_resize(sub, includes=BIG, sub_category="General")
		action = frappe.get_doc("Resource Action", result["action"])
		action.db_set("status", "Dispatching")
		frappe.db.set_value("Virtual Machine", server, action.get_resize_configuration().shape.model_dump())

		with patch("central.integrations.servers.observe_server") as observe:
			_process_locked(action.name)

		observe.assert_called_once()
		self.resize_server.assert_not_called()
		self.assertEqual(frappe.db.get_value("Resource Action", action.name, "status"), "Succeeded")

	def test_revoked_resize_permission_fails_before_dispatch(self):
		sub = self._provision()
		self._ready(sub)
		with patch("frappe.enqueue"):
			result = subscriptions.begin_resize(sub, includes=BIG, sub_category="General")

		with patch("central.integrations.servers.can", return_value=False):
			_process_locked(result["action"])

		self.assertEqual(frappe.db.get_value("Resource Action", result["action"], "status"), "Failed")
		self.resize_server.assert_not_called()
