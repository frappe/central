import frappe
from frappe.utils import add_months, get_first_day, get_last_day, getdate

from central.api import connect
from central.billing.catalog.subscriptions import active_segments, reprice_team
from central.billing.doctype.billing_profile.billing_profile import get_billing_team, get_pricing_currency
from central.billing.revenue.invoicing.generate import generate_team_invoice
from central.billing.tests.utils import (
	BillingTestCase,
	add_segment,
	complete_billing_profile,
	ensure_team,
	make_billing_subscription,
	make_plan,
	make_user,
)

CUSTOMER = "team-paid-customer"
PARTNER = "team-paying-partner"
CLUSTER = "ap-south-1"
PLAN = "bundle-partner-pays"
JUNE = ("2026-06-01", "2026-06-30")


class TestPartnerPays(BillingTestCase):
	"""A partner that pays for a customer bills the customer's usage on its own invoice, in its
	own currency, from the 1st of a month."""

	def setUp(self):
		make_plan(PLAN)
		self.customer_owner = make_user("paid.customer.owner@example.test")
		self.partner_owner = make_user("paying.partner.owner@example.test")
		ensure_team(CUSTOMER, owner=self.customer_owner)
		ensure_team(PARTNER, owner=self.partner_owner)
		complete_billing_profile(CUSTOMER, currency="INR")
		complete_billing_profile(PARTNER, currency="INR")
		frappe.db.set_value(
			"Team", PARTNER, "connect_partner_id", f"PARTNER-{frappe.generate_hash(length=6)}"
		)
		# BillingTestCase sweeps only billing records, so each test starts from no link.
		frappe.db.delete("Partner Link", {"customer_team": CUSTOMER})
		for name in frappe.get_all("Subscription", {"team": CUSTOMER}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": name})
		self.link = frappe.get_doc(
			{"doctype": "Partner Link", "customer_team": CUSTOMER, "partner_team": PARTNER}
		).insert()
		self.customer_sub = make_billing_subscription(CUSTOMER, CLUSTER, PLAN)
		add_segment(self.customer_sub, "Created", 3000, "2026-06-01 00:00:00", plan=PLAN)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_the_partner_invoice_carries_the_customer_it_pays_for(self):
		self._partner_pays(from_day=JUNE[0])
		partner_sub = make_billing_subscription(PARTNER, CLUSTER, PLAN)
		add_segment(partner_sub, "Created", 1500, "2026-06-01 00:00:00", plan=PLAN)

		self.assertIsNone(generate_team_invoice(CUSTOMER, *JUNE))
		invoice = frappe.get_doc("Invoice", generate_team_invoice(PARTNER, *JUNE))

		self.assertEqual(invoice.currency, "INR")
		self.assertEqual(invoice.subtotal, 4500)
		self.assertEqual(
			sorted((line.customer_team or "", line.amount) for line in invoice.items),
			[("", 1500), (CUSTOMER, 3000)],
		)
		self.assertEqual({line.customer_title for line in invoice.items if line.customer_team}, {CUSTOMER})

	def test_a_customer_that_pays_itself_records_its_partner(self):
		invoice = frappe.get_doc("Invoice", generate_team_invoice(CUSTOMER, *JUNE))
		self.assertEqual(invoice.partner_team, PARTNER)
		self.assertFalse(any(line.customer_team for line in invoice.items))

	def test_a_partner_pays_from_the_first_of_the_next_month_and_stops_at_month_end(self):
		today = getdate()
		frappe.set_user(self.customer_owner)
		self.link.set_payer("Partner Requested")
		frappe.set_user(self.partner_owner)
		self.link.set_payer("Partner")
		self.assertEqual(getdate(self.link.partner_pays_from), get_first_day(add_months(today, 1)))
		self.assertEqual(get_billing_team(CUSTOMER), CUSTOMER)
		self.assertEqual(get_billing_team(CUSTOMER, self.link.partner_pays_from), PARTNER)

		# Stopping before the first paid month cancels the payment.
		self.link.set_payer("Customer")
		self.assertIsNone(self.link.partner_pays_from)

		self._partner_pays(from_day=get_first_day(today))
		self.link.reload()
		frappe.set_user(self.customer_owner)
		self.link.set_payer("Customer")
		self.assertEqual(getdate(self.link.partner_pays_until), get_last_day(today))
		self.assertEqual(get_billing_team(CUSTOMER), PARTNER)
		self.assertEqual(get_billing_team(CUSTOMER, add_months(today, 1)), CUSTOMER)

	def test_only_the_right_side_changes_who_pays(self):
		frappe.set_user(self.partner_owner)
		with self.assertRaises(frappe.PermissionError):
			self.link.set_payer("Partner Requested")

		frappe.set_user(self.customer_owner)
		self.link.set_payer("Partner Requested")
		with self.assertRaises(frappe.PermissionError):
			self.link.set_payer("Partner")

		frappe.set_user(make_user("partner.pays.stranger@example.test"))
		with self.assertRaises(frappe.PermissionError):
			self.link.set_payer("Customer")
		with self.assertRaises(frappe.ValidationError):
			self.link.set_payer("Partner Requested")

	def test_ending_the_link_stops_the_partner_paying_at_month_end(self):
		today = getdate()
		self._partner_pays(from_day=get_first_day(today))
		self.link.reload()
		self.link.end("Contract ended")

		self.assertEqual(
			(self.link.payer, getdate(self.link.partner_pays_until)), ("Customer", get_last_day(today))
		)

	def test_a_payer_in_another_currency_prices_the_customer_from_the_change(self):
		complete_billing_profile(PARTNER, currency="USD")
		self._partner_pays(from_day="2026-07-01")
		self.assertEqual(get_pricing_currency(CUSTOMER, "2026-06-15"), "INR")
		self.assertEqual(get_pricing_currency(CUSTOMER, "2026-07-01"), "USD")

		reprice_team(CUSTOMER, "2026-07-01 00:00:00")
		reprice_team(CUSTOMER, "2026-07-01 00:00:00")

		(segment,) = active_segments({"team": CUSTOMER})
		self.assertEqual((segment.currency, segment.locked_rate), ("USD", 40))
		self.assertEqual(
			frappe.db.count("Subscription Change", {"subscription": self.customer_sub, "currency": "USD"}), 1
		)
		june = frappe.get_doc("Invoice", generate_team_invoice(CUSTOMER, *JUNE))
		self.assertEqual((june.currency, june.subtotal), ("INR", 3000))
		july = frappe.get_doc("Invoice", generate_team_invoice(PARTNER, "2026-07-01", "2026-07-31"))
		self.assertEqual((july.currency, july.subtotal), ("USD", 40))

	def test_a_payer_in_the_same_currency_keeps_the_locked_price(self):
		self._partner_pays(from_day="2026-07-01")
		reprice_team(CUSTOMER, "2026-07-01 00:00:00")

		(segment,) = active_segments({"team": CUSTOMER})
		self.assertEqual((segment.currency, segment.locked_rate), ("INR", 3000))

	def test_connect_reads_the_invoices_that_count_for_the_tier(self):
		own = generate_team_invoice(CUSTOMER, *JUNE)
		frappe.db.set_value("Invoice", own, {"status": "Paid", "paid_at": "2026-07-03 10:00:00"})
		integration = make_user("partner.pays.integration@example.test")
		frappe.get_doc("User", integration).add_roles("Connect Integration")

		frappe.set_user(integration)
		connect_partner_id = frappe.db.get_value("Team", PARTNER, "connect_partner_id")
		(row,) = connect.get_partner_invoices(connect_partner_id)
		self.assertEqual(
			(row.invoice, row.customer_team, row.amount, row.paid_by_partner), (own, CUSTOMER, 3000, False)
		)

	def _partner_pays(self, from_day) -> None:
		frappe.db.set_value(
			"Partner Link",
			self.link.name,
			{"payer": "Partner", "partner_pays_from": from_day, "partner_pays_until": None},
		)
