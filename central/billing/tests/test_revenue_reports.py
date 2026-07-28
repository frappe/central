# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Revenue reports — MRR/YTD, cluster-wise, and services revenue.

All three read Invoice Line Items joined to their parent invoice, so one small
fixture (two months, two clusters, a bundle line + a metered token line) exercises
every cut and lets each report be asserted against known totals.
"""

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.report.atlas_based_revenue.atlas_based_revenue import execute as cluster_execute
from central.billing.report.mrr_and_ytd_revenue.mrr_and_ytd_revenue import execute as mrr_execute
from central.billing.report.services_revenue.services_revenue import execute as services_execute
from central.billing.tests.utils import ensure_team

TEAM = "team-revenue-report"


def _invoice(period_start, period_end, items, status="Paid", currency="INR"):
	total = sum(i["amount"] for i in items)
	frappe.get_doc(
		{
			"doctype": "Invoice",
			"team": TEAM,
			"invoice_type": "Billable",
			"status": status,
			"period_start": period_start,
			"period_end": period_end,
			"currency": currency,
			"subtotal": total,
			"total": total,
			"items": items,
		}
	).insert(ignore_permissions=True)


def _bundle(amount, cluster="in-mumbai", plan=""):
	return {"resource_type": "bundle", "plan": plan, "cluster": cluster, "amount": amount, "days": 30}


def _meter(amount, resource_type="Tokens", cluster="in-mumbai"):
	return {"resource_type": resource_type, "plan": "", "cluster": cluster, "amount": amount, "quantity": 1}


class TestRevenueReports(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		self._purge()
		# May 2026: bundle 1000 (mumbai) + tokens 200 (mumbai).
		_invoice("2026-05-01", "2026-05-31", [_bundle(1000), _meter(200)])
		# Jun 2026: bundle 1000 (mumbai) + bundle 500 (dubai).
		_invoice("2026-06-01", "2026-06-30", [_bundle(1000), _bundle(500, cluster="me-dubai")])

	def tearDown(self):
		self._purge()

	def _purge(self):
		frappe.db.delete("Invoice", {"team": TEAM})

	def _rows(self, execute):
		_cols, rows, *_ = execute({"team": TEAM, "from_date": "2026-01-01", "to_date": "2026-12-31"})
		return rows

	def test_mrr_and_ytd(self):
		rows = {r["month"]: r for r in self._rows(mrr_execute)}
		# May: MRR 1000 (bundle), usage 200 (tokens), revenue 1200.
		self.assertEqual(rows["2026-05"]["mrr"], 1000.0)
		self.assertEqual(rows["2026-05"]["usage"], 200.0)
		self.assertEqual(rows["2026-05"]["revenue"], 1200.0)
		# Jun: MRR 1500 (two bundles), no usage; YTD accumulates 1200 + 1500 = 2700.
		self.assertEqual(rows["2026-06"]["mrr"], 1500.0)
		self.assertEqual(rows["2026-06"]["ytd"], 2700.0)

	def test_cluster_wise(self):
		rows = {r["cluster"]: r for r in self._rows(cluster_execute)}
		# Mumbai: 1000 + 200 + 1000 = 2200; Dubai: 500. Total 2700 → shares 81.48 / 18.52.
		self.assertEqual(rows["in-mumbai"]["revenue"], 2200.0)
		self.assertEqual(rows["me-dubai"]["revenue"], 500.0)
		self.assertEqual(rows["in-mumbai"]["share"], 81.48)
		# Region label resolves from the cluster slug.
		self.assertIn("Mumbai", rows["in-mumbai"]["region"])

	def test_services_revenue(self):
		rows = {r["family"]: r for r in self._rows(services_execute)}
		# Bundles (2500) group as compute; tokens (200) as their metered family.
		self.assertEqual(rows["VM Plans"]["revenue"], 2500.0)
		self.assertEqual(rows["VM Plans"]["kind"], "Recurring")
		self.assertEqual(rows["AI Tokens"]["revenue"], 200.0)
		self.assertEqual(rows["AI Tokens"]["kind"], "Usage")
