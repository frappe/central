# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe

from central.billing.platform import invariants, readiness
from central.billing.report.metal_server_profitability import metal_server_profitability
from central.billing.report.region_capacity import region_capacity
from central.billing.report.server_inventory import server_inventory
from central.billing.report.unit_economics import unit_economics
from central.billing.tests.utils import BillingTestCase, make_plan, seed_running_resource

REGION = "ue-region"
PLAN = "bundle-unit-economics"


def make_metal_server(name="ue-metal-1", cost=40000, vcpus=100, **values):
	return frappe.get_doc(
		{
			"doctype": "Metal Server",
			"__newname": name,
			"region": REGION,
			"vendor": "test",
			"cost_per_month_inr": cost,
			"vcpus": vcpus,
			"memory_gib": 400,
			"disk_gib": 4000,
			**values,
		}
	).insert(ignore_permissions=True)


def make_server(team: str, name: str, vcpus: float, rate: float = 1000):
	subscription = seed_running_resource(team, name, REGION, PLAN, rate=rate)
	frappe.db.set_value("Subscription", subscription, "enabled", 1)
	frappe.db.set_value("Virtual Machine", name, {"vcpus": vcpus, "status": "Running"})


def by_server(rows: list[dict]) -> dict:
	return {row["server"]: row for row in rows}


class TestMetalServer(BillingTestCase):
	def test_cost_and_vcpus_must_be_more_than_zero(self):
		make_plan(PLAN)
		seed_running_resource("team-ue-paid", "ue-probe", REGION, PLAN)
		for values in ({"cost": 0}, {"vcpus": 0}):
			with self.assertRaises(frappe.ValidationError):
				make_metal_server(name="ue-metal-zero", **values)


def seed_fleet():
	"""A paid, a free-credit and an internal server on one 100-vCPU machine at 40,000 a month."""
	make_plan(PLAN)
	make_server("team-ue-paid", "ue-paid", 4, rate=3000)
	make_server("team-ue-free", "ue-free", 2)
	make_server("team-ue-internal", "ue-internal", 4)
	make_metal_server()

	frappe.get_doc(
		{
			"doctype": "Tax Profile",
			"team": "team-ue-internal",
			"is_internal": 1,
			"internal_reason": "Ours",
		}
	).insert(ignore_permissions=True)
	frappe.get_doc(
		{
			"doctype": "Credit Ledger Entry",
			"team": "team-ue-paid",
			"entry_type": "Credit",
			"amount": 500,
			"currency": "INR",
			"reference_type": "Top-up",
		}
	).insert(ignore_permissions=True)


class TestMetalServerReserve(BillingTestCase):
	def test_the_host_reserve_must_fit_inside_the_machine(self):
		make_plan(PLAN)
		seed_running_resource("team-ue-paid", "ue-probe", REGION, PLAN)
		with self.assertRaises(frappe.ValidationError):
			make_metal_server(name="ue-metal-reserve", reserved_vcpus=100)


class TestUnitEconomics(BillingTestCase):
	def setUp(self):
		seed_fleet()

	def test_each_server_is_classed_by_who_funds_it(self):
		_, rows, *_ = server_inventory.execute({"region": REGION})
		rows = by_server(rows)

		self.assertEqual(rows["ue-paid"]["funding"], "Paying Customer")
		self.assertEqual(rows["ue-free"]["funding"], "Not Paying Yet")
		self.assertEqual(rows["ue-internal"]["funding"], "Our Own Team")

	def test_only_a_paid_server_earns_and_each_carries_its_vcpu_share(self):
		_, rows, *_ = server_inventory.execute({"region": REGION})
		rows = by_server(rows)

		# 40,000 a month over 100 vCPUs is 400 per vCPU.
		self.assertEqual(rows["ue-paid"]["cost"], 1600)
		self.assertEqual(rows["ue-paid"]["margin"], 1400)
		self.assertEqual(rows["ue-free"]["revenue"], 0)
		self.assertEqual(rows["ue-free"]["margin"], -800)

	def test_allocated_and_idle_cost_add_up_to_the_metal_bill(self):
		_, rows, *_ = unit_economics.execute({"group_by": "Funding", "region": REGION})

		self.assertEqual(sum(row["cost"] for row in rows), 40000)
		idle = next(row for row in rows if row["funding_class"] == "Idle Capacity")
		self.assertEqual(idle["vcpus"], 90)

	def test_region_capacity_reports_use_and_idle_cost(self):
		_, rows, *_ = region_capacity.execute({"region": REGION})

		self.assertEqual(rows[0]["allocated_vcpus"], 10)
		self.assertEqual(rows[0]["vcpu_used_percent"], 10)
		self.assertEqual(rows[0]["idle_cost"], 36000)

	def test_usd_revenue_needs_a_rate_for_its_margin(self):
		frappe.db.set_value("Subscription Change", {"subscription": ["is", "set"]}, "currency", "USD")
		_, rows, message, *_ = server_inventory.execute({"region": REGION})
		self.assertIsNone(by_server(rows)["ue-paid"]["margin"])
		self.assertIn("USD", message)

		_, rows, *_ = server_inventory.execute({"region": REGION, "usd_to_inr": 80})
		self.assertEqual(by_server(rows)["ue-paid"]["margin"], 3000 * 80 - 1600)

		with patch("central.billing.settings.reporting_usd_to_inr", return_value=90):
			_, rows, *_ = server_inventory.execute({"region": REGION})
		self.assertEqual(by_server(rows)["ue-paid"]["margin"], 3000 * 90 - 1600)


class TestMetalServerProfitability(BillingTestCase):
	def setUp(self):
		seed_fleet()
		frappe.db.set_value("Metal Server", "ue-metal-1", "atlas_host_id", "host-1")
		for server in ("ue-paid", "ue-free"):
			frappe.db.set_value("Virtual Machine", server, "atlas_host_id", "host-1")

	def test_a_machine_carries_its_whole_cost_against_what_its_servers_pay(self):
		_, rows, *_ = metal_server_profitability.execute({"region": REGION})
		machine = next(row for row in rows if row["metal_server"] == "ue-metal-1")

		self.assertEqual((machine["servers"], machine["paid"], machine["free_credits"]), (2, 1, 1))
		self.assertEqual(machine["vcpu_used_percent"], 6)
		self.assertEqual(machine["margin"], 3000 - 40000)

	def test_a_server_with_no_known_host_is_unplaced(self):
		_, rows, *_ = metal_server_profitability.execute({"region": REGION})
		unplaced = next(row for row in rows if not row["metal_server"])

		self.assertEqual((unplaced["servers"], unplaced["internal"]), (1, 1))
		self.assertEqual(unplaced["cost"], 0)

	def test_link_atlas_host_matches_the_host_by_title(self):
		hosts = [{"id": "host-9", "title": "ue-metal-2"}]
		machine = make_metal_server(name="ue-metal-2")
		with patch("central.integrations.atlas.AtlasClient.list_hosts", return_value=hosts):
			self.assertEqual(machine.link_atlas_host(), "host-9")

	def test_servers_on_an_unknown_host_are_found_once_per_region(self):
		[found] = [v for v in invariants.audit(only="R2", checks=readiness.CHECKS) if v.subject == REGION]
		self.assertIn("ue-internal", found.detail)
		self.assertNotIn("ue-paid", found.detail)
		self.assertEqual(found.actual, 1)


class TestRegionMetalReadiness(BillingTestCase):
	def test_a_region_with_servers_and_no_priced_metal_is_found(self):
		make_plan(PLAN)
		make_server("team-ue-free", "ue-free", 2)

		found = [v for v in invariants.audit(only="R1", checks=readiness.CHECKS) if v.subject == REGION]
		self.assertEqual(len(found), 1)

		make_metal_server()
		found = [v for v in invariants.audit(only="R1", checks=readiness.CHECKS) if v.subject == REGION]
		self.assertEqual(found, [])
