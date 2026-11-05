# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe

from central.billing.report.bare_metal_yield import bare_metal_yield
from central.billing.tests.test_unit_economics import REGION, make_metal_server, seed_fleet
from central.billing.tests.utils import BillingTestCase

RATES = {"vCPU": 500, "Memory (GiB)": 50, "Disk (GiB)": 1}

# 100 vCPUs, 400 GiB memory and 4000 GiB disk at RATES.
POTENTIAL = 100 * 500 + 400 * 50 + 4000 * 1


def run(filters: dict):
	with patch.object(bare_metal_yield, "component_rates_inr", return_value=RATES):
		return bare_metal_yield.execute({"region": REGION, **filters})


def value(vcpus: int) -> int:
	"""Rate card value of a seeded server: its vCPUs, 4 GiB memory and 40 GiB disk."""
	return vcpus * 500 + 4 * 50 + 40


class TestBareMetalYield(BillingTestCase):
	def setUp(self):
		seed_fleet()
		for server in ("ue-paid", "ue-free", "ue-internal"):
			frappe.db.set_value("Virtual Machine", server, {"memory_megabytes": 4096, "disk_gigabytes": 40})

	def test_potential_splits_into_unsold_unpaid_discount_and_cash(self):
		_, rows, *_ = run({"group_by": "Region"})
		row = rows[0]

		self.assertEqual(row["potential"], POTENTIAL)
		self.assertEqual(row["unsold"], POTENTIAL - value(4) - value(2) - value(4))
		self.assertEqual(row["unpaid"], value(2) + value(4))
		# The paying server pays 3000, above its rate card value, so the discount is negative.
		self.assertEqual(row["discount"], value(4) - 3000)
		self.assertEqual(row["revenue"], 3000)
		self.assertEqual(row["unsold"] + row["unpaid"] + row["discount"] + row["revenue"], row["potential"])
		self.assertEqual(row["yield_percent"], 4.1)

	def test_servers_that_pay_nothing_cost_their_metal_share_not_their_rate_card(self):
		_, rows, _, _, summary = run({"group_by": "Region"})

		# 40,000 a month over 100 vCPUs is 400 a vCPU; the free and internal servers hold 6.
		self.assertEqual(rows[0]["unpaid_cost"], 6 * 400)
		self.assertLess(rows[0]["unpaid_cost"], rows[0]["unpaid"])
		cost = next(card for card in summary if card["label"] == "Cost of Servers That Pay Nothing (INR)")
		self.assertEqual(cost["value"], 6 * 400)

	def test_a_machine_row_holds_only_the_servers_on_its_host(self):
		frappe.db.set_value("Metal Server", "ue-metal-1", "atlas_host_id", "host-1")
		for server in ("ue-paid", "ue-free"):
			frappe.db.set_value("Virtual Machine", server, "atlas_host_id", "host-1")

		_, rows, message, *_ = run({"group_by": "Metal Server"})
		machine = next(row for row in rows if row["group"] == "ue-metal-1")
		unplaced = next(row for row in rows if not row["group"])

		self.assertEqual(machine["servers"], 2)
		self.assertEqual(machine["unsold"], POTENTIAL - value(4) - value(2))
		self.assertEqual((unplaced["potential"], unplaced["unpaid"]), (0, value(4)))
		self.assertIn("no known machine", message)

	def test_a_machine_row_prices_servers_that_pay_nothing_off_its_own_cost(self):
		make_metal_server(name="ue-metal-2", cost=10000, vcpus=100, atlas_host_id="host-2")
		frappe.db.set_value("Virtual Machine", "ue-free", "atlas_host_id", "host-2")

		_, rows, *_ = run({"group_by": "Metal Server"})
		machine = next(row for row in rows if row["group"] == "ue-metal-2")

		# 10,000 a month over 100 vCPUs is 100 a vCPU, not the region's 250; the free server holds 2.
		self.assertEqual(machine["unpaid_cost"], 2 * 100)

	def test_usd_revenue_needs_a_rate_for_its_yield(self):
		frappe.db.set_value("Subscription Change", {"subscription": ["is", "set"]}, "currency", "USD")
		_, rows, message, *_ = run({"group_by": "Region"})
		self.assertIsNone(rows[0]["yield_percent"])
		self.assertIn("USD", message)

		_, rows, *_ = run({"group_by": "Region", "usd_to_inr": 80})
		self.assertEqual(rows[0]["revenue"], 3000 * 80)
