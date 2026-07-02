# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Resize a composed config: changed-event re-lock at current rates (#82)."""

from unittest.mock import call, patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import get_first_day, get_last_day, nowdate

from central.billing.api.admin.catalog import update_component_rate
from central.billing.catalog import subscriptions
from central.billing.catalog.pricing import set_catalog_rate
from central.billing.revenue.invoicing import generate_team_invoice
from central.billing.tests.utils import (
	complete_billing_profile,
	ensure_atlas_instance,
	ensure_team,
	make_plan,
	run_enqueued_inline,
	set_team_tier,
)

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
				"doctype": "Trust Tier Level", "__newname": name, "tier": name,
				"sequence": 1, "is_default": 0, "max_resource_count": 50, "min_paid_invoices": 0,
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
		# A resize now drives the real VM on its Atlas (#54) then resumes it. Stub both
		# outbound calls so these billing-logic tests stay hermetic; tests that care
		# assert against them.
		resize_patcher = patch("central.integrations.atlas.AtlasClient.resize_vm", return_value="task-1")
		action_patcher = patch("central.integrations.atlas.AtlasClient.vm_action", return_value="task-2")
		self.resize_vm = resize_patcher.start()
		self.vm_action = action_patcher.start()
		self.addCleanup(resize_patcher.stop)
		self.addCleanup(action_patcher.stop)

	def _ready(self, sub):
		"""Mark a subscription's VM Stopped — the state a resize requires (Firecracker
		can't reconfigure a running machine). Returns the asset id."""
		asset = frappe.db.get_value("Subscription", sub, "asset_id")
		frappe.db.set_value("Asset", asset, "status", "Stopped")
		return asset

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
		self.resize_vm.assert_not_called()  # refused before the VM is touched
		self.assertEqual(len(self._segments(sub)), 1)  # no new segment opened

	def test_resize_records_nothing_on_cancelled(self):
		sub = self._provision()
		subscriptions.cancel_subscription(sub)
		result = subscriptions.resize_composed_subscription(sub, BIG, "General")
		self.assertIsNone(result)
		self.assertEqual(len(self._segments(sub)), 1)

	def test_resize_records_nothing_on_terminated(self):
		sub = self._provision()
		asset = frappe.db.get_value("Subscription", sub, "asset_id")
		frappe.db.set_value("Asset", asset, "status", "Terminated")
		result = subscriptions.resize_composed_subscription(sub, BIG, "General")
		self.assertIsNone(result)
		self.assertEqual(len(self._segments(sub)), 1)

	def test_resize_stops_running_vm_then_starts_it_back(self):
		sub = self._provision()
		asset = frappe.db.get_value("Subscription", sub, "asset_id")
		frappe.db.set_value("Asset", asset, "status", "Running")
		subscriptions.resize_composed_subscription(sub, BIG, "General")
		# A live VM is stopped, resized, then started back up — the power-cycle returns
		# it to the running state the user found it in (never left silently powered off).
		self.resize_vm.assert_called_once()
		self.assertEqual(self.vm_action.call_args_list, [call(asset, "stop"), call(asset, "start")])
		self.assertEqual(len(self._segments(sub)), 2)  # re-priced

	def test_resize_drives_atlas_with_new_shape(self):
		sub = self._provision()
		self._ready(sub)  # Stopped: no stop needed, just resize
		subscriptions.resize_composed_subscription(sub, BIG, "General")
		self.resize_vm.assert_called_once()
		# BIG is 4 vCPU / 16 GB RAM / 40 GB disk — memory carried in megabytes.
		self.assertEqual(
			self.resize_vm.call_args.kwargs,
			{"vcpus": 4, "memory_megabytes": 16 * 1024, "disk_gigabytes": 40},
		)
		self.vm_action.assert_not_called()  # already off — no power step

	def test_resize_rejects_disk_shrink_without_touching_vm(self):
		sub = self._provision()  # SMALL — 40 GB disk
		asset = self._ready(sub)
		frappe.db.set_value("Asset", asset, "disk_gigabytes", 100)  # server grew to 100 GB
		with self.assertRaisesRegex(frappe.ValidationError, "Disk can't shrink"):
			subscriptions.resize_composed_subscription(sub, BIG, "General")  # BIG is 40 GB < 100
		# Refused before any power change — the VM is never stopped or resized.
		self.vm_action.assert_not_called()
		self.resize_vm.assert_not_called()
		self.assertEqual(len(self._segments(sub)), 1)  # no re-price

	def test_failed_reshape_restarts_a_running_vm(self):
		sub = self._provision()  # 40 GB disk, so BIG (40) is not a shrink
		asset = frappe.db.get_value("Subscription", sub, "asset_id")
		frappe.db.set_value("Asset", asset, "status", "Running")
		self.resize_vm.side_effect = frappe.ValidationError("host boom")
		with self.assertRaises(frappe.ValidationError):
			subscriptions.resize_composed_subscription(sub, BIG, "General")
		# Stopped to resize, the resize failed, so it's started back — not left off.
		self.assertEqual(self.vm_action.call_args_list, [call(asset, "stop"), call(asset, "start")])
		self.assertEqual(len(self._segments(sub)), 1)  # no re-price on failure

	def test_restart_failure_after_successful_resize_is_logged_not_raised(self):
		sub = self._provision()
		asset = frappe.db.get_value("Subscription", sub, "asset_id")
		frappe.db.set_value("Asset", asset, "status", "Running")
		# stop() succeeds, the resize lands, but the auto-restart fails. The resize has
		# already succeeded, so we log and carry on — the re-price still opens, worst case
		# a resized-but-stopped VM the user can start by hand (never a lost resize).
		self.vm_action.side_effect = ["task-stop", frappe.ValidationError("start boom")]
		subscriptions.resize_composed_subscription(sub, BIG, "General")
		self.assertEqual(self.vm_action.call_args_list, [call(asset, "stop"), call(asset, "start")])
		self.assertEqual(len(self._segments(sub)), 2)  # re-priced despite the failed restart

	def test_resize_to_preset_plan_reshapes_and_relocks(self):
		sub = self._provision()
		asset = self._ready(sub)  # Stopped
		plan = make_plan("resize-target", rates=[{"cluster": "", "currency": "INR", "rate": 1500}])
		subscriptions.resize_to_plan(sub, plan)
		doc = frappe.get_doc("Subscription", sub)
		self.assertEqual((doc.pricing_mode, doc.plan), ("Preset", plan))
		# The bundle's shape (DEFAULT_INCLUDES) drives the VM resize; no power step.
		self.resize_vm.assert_called_once_with(asset, vcpus=2, memory_megabytes=4096, disk_gigabytes=80)
		self.vm_action.assert_not_called()
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

	def test_begin_resize_flags_the_vm_and_defers_the_reshape(self):
		sub = self._provision()
		asset = self._ready(sub)
		with patch("frappe.enqueue") as enqueue:
			result = subscriptions.begin_resize(sub, includes=BIG, sub_category="General")
		self.assertEqual(result, {"queued": True, "resized": True})
		enqueue.assert_called_once()  # the slow reshape is deferred, not run in-request
		self.resize_vm.assert_not_called()
		# The VM is flagged Resizing so the console shows it and blocks power actions.
		self.assertEqual(frappe.db.get_value("Asset", asset, "resize_in_progress"), 1)
		self.assertEqual(len(self._segments(sub)), 1)  # billing re-locks only in the job

	def test_begin_resize_job_reshapes_relocks_and_clears_flag(self):
		sub = self._provision()
		asset = self._ready(sub)
		with patch("frappe.enqueue", side_effect=run_enqueued_inline):
			subscriptions.begin_resize(sub, includes=BIG, sub_category="General")
		self.resize_vm.assert_called_once()  # the deferred job drove the real resize
		self.assertEqual(frappe.db.get_value("Asset", asset, "resize_in_progress"), 0)
		self.assertEqual(len(self._segments(sub)), 2)  # re-priced once the job landed

	def test_begin_resize_is_a_noop_on_the_same_config(self):
		sub = self._provision()
		self._ready(sub)
		with patch("frappe.enqueue") as enqueue:
			result = subscriptions.begin_resize(sub, includes=SMALL, sub_category="General")
		self.assertEqual(result, {"queued": False, "resized": False})
		enqueue.assert_not_called()
		self.resize_vm.assert_not_called()

	def test_begin_resize_rejects_disk_shrink_synchronously(self):
		sub = self._provision()  # SMALL — 40 GB disk
		asset = self._ready(sub)
		frappe.db.set_value("Asset", asset, "disk_gigabytes", 100)  # server grew to 100 GB
		with patch("frappe.enqueue") as enqueue:
			with self.assertRaisesRegex(frappe.ValidationError, "Disk can't shrink"):
				subscriptions.begin_resize(sub, includes=BIG, sub_category="General")  # BIG is 40 GB
		enqueue.assert_not_called()  # refused before anything is queued
		self.assertEqual(frappe.db.get_value("Asset", asset, "resize_in_progress"), 0)

	def test_begin_resize_rejects_over_headroom_preset_synchronously(self):
		sub = self._provision()
		asset = self._ready(sub)
		set_team_tier(TEAM, max_spend=4000)
		plan = make_plan("over-headroom-sync", rates=[{"cluster": "", "currency": "INR", "rate": 5000}])
		with patch("frappe.enqueue") as enqueue:
			with self.assertRaises(frappe.ValidationError):
				subscriptions.begin_resize(sub, plan=plan)
		enqueue.assert_not_called()  # rejected up front, nothing queued
		self.assertEqual(frappe.db.get_value("Asset", asset, "resize_in_progress"), 0)

	def test_begin_resize_refuses_a_second_resize_while_one_is_running(self):
		sub = self._provision()
		asset = self._ready(sub)
		frappe.db.set_value("Asset", asset, "resize_in_progress", 1)  # already resizing
		with patch("frappe.enqueue") as enqueue:
			with self.assertRaisesRegex(frappe.ValidationError, "already resizing"):
				subscriptions.begin_resize(sub, includes=BIG, sub_category="General")
		enqueue.assert_not_called()

	def test_begin_resize_relocks_inline_when_there_is_no_live_vm(self):
		sub = self._provision()  # asset defaults to Pending (never started)
		with patch("frappe.enqueue") as enqueue:
			result = subscriptions.begin_resize(sub, includes=BIG, sub_category="General")
		self.assertEqual(result, {"queued": False, "resized": True})
		enqueue.assert_not_called()  # nothing slow to defer
		self.resize_vm.assert_not_called()  # no VM to reshape (Pending)
		self.assertEqual(len(self._segments(sub)), 2)  # re-priced inline

	def test_apply_resize_clears_flag_and_reraises_when_the_reshape_fails(self):
		sub = self._provision()
		asset = self._ready(sub)
		frappe.db.set_value("Asset", asset, "resize_in_progress", 1)
		self.resize_vm.side_effect = frappe.ValidationError("host boom")
		# The job rolls back + commits the flag clear; mock those so the test transaction
		# stays isolated while we assert the flag-clearing + re-raise behaviour.
		with patch("frappe.db.rollback"), patch("frappe.db.commit"):
			with self.assertRaises(frappe.ValidationError):
				subscriptions._apply_resize(sub, includes=BIG, sub_category="General", asset_id=asset)
		self.assertEqual(frappe.db.get_value("Asset", asset, "resize_in_progress"), 0)
		self.assertEqual(len(self._segments(sub)), 1)  # billing stayed on the old segment
