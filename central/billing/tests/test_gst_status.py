# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""GSTIN status: stored from the GST portal, refreshed in a paced sweep."""

from unittest.mock import patch

import frappe

from central.billing.revenue import gst_status
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import complete_billing_profile, ensure_team

GSTIN = "27AAPFU0939F1ZV"
LOOKUP = "central.billing.ingester.customer.get_gstin_details"


def profile_with_gstin(team, status=None, checked_days_ago=None):
	ensure_team(team)
	complete_billing_profile(team)
	checked_at = (
		frappe.utils.add_days(frappe.utils.now_datetime(), -checked_days_ago)
		if checked_days_ago is not None
		else None
	)
	frappe.db.set_value(
		"Billing Profile",
		team,
		{"gstin": GSTIN, "gst_status": status, "gst_status_checked_at": checked_at},
	)
	return team


class GstStatusTestCase(IntegrationTestCase):
	def setUp(self):
		self._conf = patch.dict(frappe.local.conf, {"enable_erpnext_sync": 1})
		self._conf.start()
		self._pace = patch.object(gst_status, "PACE_SECONDS", 0)
		self._pace.start()
		self._customer_sync = patch("central.billing.ingester.customer._enqueue")
		self._customer_sync.start()

	def tearDown(self):
		self._customer_sync.stop()
		self._pace.stop()
		self._conf.stop()


class TestStore(GstStatusTestCase):
	def test_stores_status_category_and_time(self):
		team = profile_with_gstin("team-gst-store")
		gst_status.store(team, GSTIN, {"status": "cancelled", "gst_category": "SEZ"})
		row = frappe.db.get_value(
			"Billing Profile", team, ["gst_status", "gst_category", "gst_status_checked_at"], as_dict=True
		)
		self.assertEqual(row.gst_status, "Cancelled")
		self.assertEqual(row.gst_category, "SEZ")
		self.assertTrue(row.gst_status_checked_at)

	def test_unknown_status_keeps_the_old_one(self):
		team = profile_with_gstin("team-gst-unknown", status="Active")
		gst_status.store(team, GSTIN, {"status": "Provision"})
		self.assertEqual(frappe.db.get_value("Billing Profile", team, "gst_status"), "Active")

	def test_answer_for_an_old_gstin_is_dropped(self):
		team = profile_with_gstin("team-gst-race", status="Active")
		gst_status.store(team, "29AAPFU0939F1ZV", {"status": "Cancelled"})
		self.assertEqual(frappe.db.get_value("Billing Profile", team, "gst_status"), "Active")


class TestStanding(GstStatusTestCase):
	def test_lapsed_statuses_hide_the_gstin(self):
		for status in gst_status.LAPSED:
			team = profile_with_gstin("team-gst-standing", status=status)
			self.assertEqual(gst_status.standing(team), {"gstin": None, "lapsed": True})

	def test_active_and_unchecked_keep_the_gstin(self):
		for status in ("Active", None):
			team = profile_with_gstin("team-gst-standing", status=status)
			self.assertEqual(gst_status.standing(team), {"gstin": GSTIN, "lapsed": False})


class TestSweep(GstStatusTestCase):
	def test_picks_unchecked_and_stale_oldest_first(self):
		fresh = profile_with_gstin("team-gst-fresh", "Active", checked_days_ago=1)
		stale = profile_with_gstin("team-gst-stale", "Active", checked_days_ago=30)
		never = profile_with_gstin("team-gst-never")
		teams = gst_status.stale_teams(limit=1000)
		self.assertNotIn(fresh, teams)
		self.assertLess(teams.index(never), teams.index(stale))

	def test_respects_the_daily_limit(self):
		for n in range(3):
			profile_with_gstin(f"team-gst-limit-{n}")
		with (
			patch("central.billing.settings.gst_status_daily_limit", return_value=2),
			patch(LOOKUP, return_value={"status": "Active"}) as lookup,
		):
			gst_status.refresh_stale()
		self.assertEqual(lookup.call_count, 2)

	def test_stops_after_failures_in_a_row(self):
		for n in range(gst_status.MAX_FAILURES_IN_A_ROW + 3):
			profile_with_gstin(f"team-gst-down-{n}")
		with patch(LOOKUP, side_effect=ConnectionError("portal down")) as lookup:
			result = gst_status.refresh_stale()
		self.assertEqual(lookup.call_count, gst_status.MAX_FAILURES_IN_A_ROW)
		self.assertEqual(result["failed"], gst_status.MAX_FAILURES_IN_A_ROW)

	def test_does_nothing_when_lookups_are_off(self):
		profile_with_gstin("team-gst-off")
		frappe.local.conf["enable_erpnext_sync"] = 0
		with patch(LOOKUP) as lookup:
			self.assertEqual(gst_status.refresh_stale()["skipped"], "lookups_off")
		lookup.assert_not_called()


class TestRecheck(GstStatusTestCase):
	def test_recent_check_is_answered_from_the_store(self):
		team = profile_with_gstin("team-gst-recheck", "Cancelled", checked_days_ago=0)
		with patch(LOOKUP) as lookup:
			self.assertEqual(gst_status.recheck(team), "Cancelled")
		lookup.assert_not_called()

	def test_old_check_asks_the_portal(self):
		team = profile_with_gstin("team-gst-recheck", "Cancelled", checked_days_ago=1)
		with patch(LOOKUP, return_value={"status": "Active"}):
			self.assertEqual(gst_status.recheck(team), "Active")


class TestGstinChange(GstStatusTestCase):
	def test_new_gstin_forgets_the_old_status(self):
		team = profile_with_gstin("team-gst-change", "Cancelled", checked_days_ago=1)
		doc = frappe.get_doc("Billing Profile", team)
		doc.gstin = "27AAACR5055K1Z7"
		with patch("frappe.enqueue") as enqueue:
			doc.save(ignore_permissions=True)
		row = frappe.db.get_value(
			"Billing Profile", team, ["gst_status", "gst_status_checked_at"], as_dict=True
		)
		self.assertFalse(row.gst_status)
		self.assertFalse(row.gst_status_checked_at)
		methods = [c.args[0] for c in enqueue.call_args_list]
		self.assertIn("central.billing.revenue.gst_status.refresh", methods)
