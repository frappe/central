# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe

from central.billing.report._telemetry import Telemetry
from central.billing.report.allocation_vs_usage import allocation_vs_usage
from central.billing.report.bare_metal_capacity import bare_metal_capacity
from central.billing.report.bare_metal_roi import bare_metal_roi
from central.billing.report.customer_profitability import customer_profitability
from central.billing.report.service_profitability import service_profitability
from central.billing.report.stranded_capacity import stranded_capacity
from central.billing.report.vm_packing_matrix import vm_packing_matrix
from central.billing.tests.test_unit_economics import REGION, make_metal_server, seed_fleet
from central.billing.tests.utils import BillingTestCase

HOST = "host-1"


def line(team, service, amount, cost=0.0, **values):
	base = {"quantity": 0, "days": 0, "hours": 0, "vcpus": 0, "unit": None}
	return frappe._dict(base, team=team, service=service, revenue_inr=amount, cost_inr=cost, **values)


def no_telemetry():
	return patch.multiple(Telemetry, servers=lambda self, servers: {}, hosts=lambda self, machines: {})


class TestMoneyReports(BillingTestCase):
	def test_customer_profit_is_revenue_less_direct_cost_per_team(self):
		lines = [
			line("team-a", "VM Plans", 1000, 400),
			line("team-a", "AI Tokens", 300, 100),
			line("team-b", "VM Plans", 200, 500),
		]
		with patch("central.billing.report._economics.BilledMonth._load", return_value=lines), no_telemetry():
			_, rows, *_ = customer_profitability.execute({"month": "2026-10-01"})
		rows = {row["group"]: row for row in rows}

		self.assertEqual((rows["team-a"]["vm_revenue"], rows["team-a"]["service_revenue"]), (1000, 300))
		self.assertEqual(rows["team-a"]["gross_profit"], 800)
		self.assertEqual(rows["team-b"]["gross_profit"], -300)

	def test_service_price_and_cost_read_per_unit(self):
		lines = [
			line("team-a", "AI Tokens", 500, 200, quantity=1000, unit="Nos"),
			line("team-b", "AI Tokens", 500, 200, quantity=1000, unit="Nos"),
		]
		with patch("central.billing.report._economics.BilledMonth._load", return_value=lines):
			_, rows, *_ = service_profitability.execute({"month": "2026-10-01"})

		self.assertEqual((rows[0]["customers"], rows[0]["usage"]), (2, 2000))
		self.assertEqual((rows[0]["revenue_per_unit"], rows[0]["cost_per_unit"]), (0.5, 0.2))
		self.assertEqual(rows[0]["margin"], 60)


class TestCapacityReports(BillingTestCase):
	def setUp(self):
		seed_fleet()
		frappe.db.set_value(
			"Metal Server",
			"ue-metal-1",
			{"atlas_host_id": HOST, "memory_gib": 400, "reserved_vcpus": 20, "cpu_overcommit_ratio": 2},
		)
		for server in ("ue-paid", "ue-free"):
			frappe.db.set_value("Virtual Machine", server, "atlas_host_id", HOST)

	def test_sellable_takes_off_the_reserve_and_applies_the_overcommit(self):
		with no_telemetry():
			_, rows, *_ = bare_metal_capacity.execute({"region": REGION})
		vcpu = next(row for row in rows if row["resource"] == "vCPU")

		self.assertEqual(vcpu["sellable"], (100 - 20) * 2)
		self.assertEqual(vcpu["allocated"], 6)
		self.assertEqual(vcpu["remaining"], 154)

	def test_atlas_allocation_counts_platform_servers(self):
		hosts = {
			HOST: {
				"cpu_percent": 10,
				"memory_used_gib": 50,
				"allocated_vcpus": 30,
				"allocated_memory_gib": 0,
				"allocated_disk_gib": 0,
			}
		}
		with patch.multiple(Telemetry, servers=lambda self, s: {}, hosts=lambda self, m: hosts):
			_, rows, *_ = bare_metal_capacity.execute({"region": REGION})
		vcpu = next(row for row in rows if row["resource"] == "vCPU")

		self.assertEqual((vcpu["allocated"], vcpu["platform"]), (30, 24))
		self.assertEqual(vcpu["used"], 10)

	def test_the_most_allocated_resource_binds_and_strands_the_rest(self):
		frappe.db.set_value("Virtual Machine", "ue-paid", "memory_megabytes", 0)
		with no_telemetry():
			_, rows, *_ = stranded_capacity.execute({"region": REGION})

		self.assertEqual(rows[0]["binding"], "vCPU")
		self.assertEqual(rows[0]["memory_stranded_percent"], 100)

	def test_a_plan_fits_until_its_scarcest_resource_runs_out(self):
		with no_telemetry():
			_, rows, *_ = vm_packing_matrix.execute({"region": REGION})
		row = next(row for row in rows if row["plan"] == "bundle-unit-economics")

		# 160 sellable vCPUs / 2 = 80, 400 GiB / 4 = 100, 4000 GiB disk / 80 = 50.
		self.assertEqual((row["fit_by_vcpu"], row["fit_by_memory"], row["fit_by_disk"]), (80, 100, 50))
		self.assertEqual((row["max_per_machine"], row["binding"]), (50, "Disk"))
		self.assertEqual(row["current"], 2)

	def test_unused_vcpus_sit_above_the_peak(self):
		usage = {
			"ue-paid": {
				"cpu_percent": 10,
				"cpu_peak_percent": 25,
				"memory_used_gib": 1,
				"disk_used_gib": 1,
				"bandwidth_gib_month": 0,
			}
		}
		with patch.multiple(Telemetry, servers=lambda self, s: usage, hosts=lambda self, m: {}):
			_, rows, message, *_ = allocation_vs_usage.execute({"region": REGION})

		self.assertEqual([row["server"] for row in rows], ["ue-paid"])
		self.assertEqual(rows[0]["unused_vcpus"], 3)
		self.assertIn("2 live server(s) do not report usage", message)

	def test_an_owned_machine_pays_back_its_purchase_price(self):
		make_metal_server(
			name="ue-metal-owned",
			ownership="Owned",
			purchase_price_inr=120000,
			purchased_on="2026-01-01",
			deployed_on=frappe.utils.add_months(frappe.utils.getdate(), -2),
		)
		_, rows, *_ = bare_metal_roi.execute({"region": REGION})
		row = next(row for row in rows if row["metal_server"] == "ue-metal-owned")

		self.assertEqual(row["purchase_price"], 120000)
		self.assertGreater(row["running_cost"], 0)
		self.assertIsNone(row["payback_months"])  # it has earned nothing, so it never pays back


class TestTelemetry(BillingTestCase):
	def test_a_region_without_a_source_gives_no_usage_and_says_so(self):
		frappe.get_doc({"doctype": "Region", "region": "telemetry-less", "status": "Active"}).insert(
			ignore_permissions=True
		)
		telemetry = Telemetry()

		self.assertEqual(telemetry.servers([frappe._dict(name="server-1", region="telemetry-less")]), {})
		self.assertEqual(telemetry.gaps, ["telemetry-less"])

	def test_an_unsafe_id_never_reaches_the_query(self):
		telemetry = Telemetry()
		with patch.object(Telemetry, "_query", return_value=[]) as query:
			telemetry.servers([frappe._dict(name="x'); DROP TABLE samples; --", region="mumbai")])
		query.assert_not_called()
