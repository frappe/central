from datetime import timedelta
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.integrations.metrics import CentralMetrics
from central.signups import metrics as signup_metrics


def get_values(metrics: CentralMetrics, metric: str, label: str) -> dict:
	return {
		sample["labels"][label]: sample["value"] for sample in metrics.samples if sample["metric"] == metric
	}


class TestSignupMetrics(IntegrationTestCase):
	def test_signups_report_the_funnel_setup_time_and_waiting_trial(self) -> None:
		now = frappe.utils.now_datetime()
		failed = frappe._dict(
			product="crm",
			title="acme.frappe.cloud",
			subdomain="acme",
			error_code="ATLAS_REJECTED",
			status="Failed",
		)
		ready = [
			frappe._dict(
				region="bom", product="crm", requested_at=now, ready_at=now + timedelta(seconds=seconds)
			)
			for seconds in (10, 20, 90)
		]
		waiting = [frappe._dict(region="bom", oldest=now - timedelta(minutes=10))]
		with (
			patch("central.signups.metrics.frappe.db.count", return_value=4),
			patch("central.signups.metrics.frappe.get_all", side_effect=[["crm", "crm", None], [failed]]),
			patch("central.signups.metrics.get_ready_signups", return_value=ready),
			patch("central.signups.metrics.get_waiting_signups", return_value=waiting),
		):
			metrics = CentralMetrics()
			signup_metrics.add_signup_metrics(metrics)

		steps = {
			(sample["labels"]["step"], sample["labels"]["product"]): sample["value"]
			for sample in metrics.samples
			if sample["metric"] == "central_signup_steps_last_hour"
		}
		self.assertEqual(
			steps,
			{
				("verified", "none"): 4.0,
				("requested", "crm"): 2.0,
				("requested", "none"): 1.0,
				("ready", "crm"): 3.0,
				("failed", "crm"): 1.0,
			},
		)
		self.assertEqual(
			get_values(metrics, "central_signup_setup_seconds", "quantile"), {"p50": 20.0, "max": 90.0}
		)
		self.assertEqual(
			get_values(metrics, "central_signup_ready_within_last_hour", "le"),
			{"30": 2.0, "60": 2.0, "120": 3.0, "300": 3.0, "600": 3.0},
		)
		self.assertEqual(get_values(metrics, "central_signup_failed", "site"), {"acme.frappe.cloud": 1.0})
		waiting_age = get_values(metrics, "central_signup_oldest_waiting_seconds", "region")["bom"]
		self.assertAlmostEqual(waiting_age, 600, delta=10)

	def test_card_setups_count_outcomes_and_name_teams_that_cannot_finish(self) -> None:
		now = frappe.utils.now_datetime()
		recent, old = now - timedelta(minutes=5), now - timedelta(days=2)

		def setup(
			team: str, status: str, creation=recent, validated_at=None, failure_code=None
		) -> frappe._dict:
			return frappe._dict(
				team=team,
				gateway="Stripe",
				method_type="Card",
				status=status,
				creation=creation,
				validated_at=validated_at,
				failure_code=failure_code,
				decline_code=None,
			)

		setups = [
			setup("TEAM-1", "Failed", failure_code="mandate_inactive"),
			setup("TEAM-1", "Pending Validation"),
			setup("TEAM-2", "Cancelled"),
			setup("TEAM-2", "Active", validated_at=recent),
			setup("TEAM-3", "Expired", creation=old),
			setup("TEAM-4", "Failed", creation=old, validated_at=old),
		]
		pending = [frappe._dict(gateway="Stripe", creation=now - timedelta(hours=2))]
		with patch("central.signups.metrics.frappe.get_all", side_effect=[setups, pending]):
			metrics = CentralMetrics()
			signup_metrics.add_card_setup_metrics(metrics)

		self.assertEqual(
			get_values(metrics, "central_card_setups_last_hour", "outcome"),
			{"started": 4.0, "failed": 1.0, "succeeded": 1.0, "expired": 1.0},
		)
		self.assertEqual(get_values(metrics, "central_card_setup_failed", "code"), {"mandate_inactive": 1.0})
		self.assertEqual(
			get_values(metrics, "central_card_setup_unfinished_attempts", "team"), {"TEAM-1": 2.0}
		)
		pending_age = get_values(metrics, "central_card_setup_oldest_pending_seconds", "gateway")["Stripe"]
		self.assertAlmostEqual(pending_age, 7200, delta=10)
