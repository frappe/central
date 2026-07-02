# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Resize a composed config: changed-event re-lock at current rates (#82)."""

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


class TestResizeComposed(IntegrationTestCase):
	def setUp(self):
		ensure_atlas_instance(CLUSTER)
		ensure_team(TEAM)
		complete_billing_profile(TEAM, currency="INR")
		set_team_tier(TEAM, max_spend=1_000_000)
		for resource_type, rate in (("Compute", 500), ("Memory", 250), ("Disk", 10)):
			set_catalog_rate("Resource Type", resource_type, "INR", rate)
		for name in frappe.get_all("Subscription", filters={"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": name})
			frappe.delete_doc("Subscription", name, force=True)
		frappe.db.delete("Invoice", {"team": TEAM})

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

	def test_slide_off_preset_opens_composed_segment(self):
		plan = make_plan("preset-slide", rates=[{"cluster": "", "currency": "INR", "rate": 1500}])
		sub = subscriptions.create_subscription(TEAM, CLUSTER, plan=plan).name
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
