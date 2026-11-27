# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""A server moved to another team bills each public IPv4 day once, on one of its subscriptions."""

import frappe

from central.billing.revenue import usage_segments
from central.billing.revenue.invoicing.generate import generate_team_invoice
from central.billing.tests.test_ipv4_days import CLUSTER, JUNE, VM_PLAN, IPv4DaysTestCase, at
from central.billing.tests.utils import add_segment, make_billing_subscription, usage_days
from central.services.doctype.service.service import NETWORK_SERVICE

# The team edit lands at noon on the 10th, so both subscriptions bill the server that day.
MOVED_AT = at("2026-06-10", hours=12)


class TestIPv4TeamEdit(IPv4DaysTestCase):
	team = "team-ipv4-edit-old"
	server = "ipv4-edit-vm"
	new_team = "team-ipv4-edit-new"

	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.db.delete, "Virtual Machine", {"name": self.server})
		self.hold(at("2026-06-01"))

	def move_server(self) -> None:
		"""Move the server to the new team, as a team edit does: one subscription ends, the next starts."""
		add_segment(self.subscription, "Cancelled", None, MOVED_AT)
		self.new_subscription = make_billing_subscription(
			self.new_team, CLUSTER, VM_PLAN, resource_id=self.server, currency=self.currency
		)
		add_segment(self.new_subscription, "Created", 1000, MOVED_AT, plan=VM_PLAN, currency=self.currency)
		frappe.db.set_value("Virtual Machine", self.server, "team", self.new_team)

	def days_on(self, subscription: str) -> list[str]:
		rows = usage_days(service=NETWORK_SERVICE, subject=self.server, subscription=subscription)
		return [str(row.day) for row in rows]

	def ip_quantity(self, team: str) -> float:
		invoice = frappe.get_doc("Invoice", generate_team_invoice(team, "2026-06-01", "2026-06-30"))
		return sum(line.quantity for line in invoice.items if line.resource_type == "IP")

	def test_a_written_day_is_not_written_again_on_the_next_subscription(self):
		usage_segments.project([self.server], JUNE[0], JUNE[9])
		self.move_server()

		usage_segments.project([self.server], JUNE[0], JUNE[-1])

		self.assertEqual(self.days_on(self.subscription), JUNE[:10])
		self.assertEqual(self.days_on(self.new_subscription), JUNE[10:])
		self.assertAlmostEqual(self.ip_quantity(self.team) + self.ip_quantity(self.new_team), 30 / 30)

	def test_a_day_two_subscriptions_bill_goes_to_the_earlier_one(self):
		self.move_server()

		usage_segments.project([self.server], JUNE[0], JUNE[-1])

		self.assertEqual(self.days_on(self.subscription), JUNE[:10])
		self.assertEqual(self.days_on(self.new_subscription), JUNE[10:])

	def test_the_new_team_draft_writes_the_days_of_a_server_moved_to_it(self):
		self.move_server()

		# The segment still names the old team; the draft finds the server by its subscription.
		self.assertAlmostEqual(self.ip_quantity(self.new_team), 20 / 30)
		self.assertEqual(self.days_on(self.new_subscription), JUNE[10:])
