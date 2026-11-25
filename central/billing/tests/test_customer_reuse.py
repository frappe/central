# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""A customer that already exists in the accounting system is used again, never made twice."""

from unittest.mock import patch

import frappe

from central.billing.api.admin import accounting
from central.billing.ingester import customer
from central.billing.tests.accounting_fake import configure_accounting, requires_accounting_system, sync_mode
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import complete_billing_profile, ensure_team

TEAM = "team-customer-reuse"
EMAIL = "billing@test.example"  # the billing email complete_billing_profile sets
POST = "central.billing.ingester.customer.post"
PUT = "central.billing.ingester.customer.put"


class Remote:
	"""Customers, contacts and addresses that Press v1 made, answered the way the REST API does."""

	def __init__(self):
		self.records = {}

	def add_customer(self, name, customer_name=f"{TEAM} Ltd", currency="INR", city="Pune", email=EMAIL):
		self.records[("Customer", name)] = {"customer_name": customer_name, "default_currency": currency}
		self.records[("Contact", f"{name}-contact")] = {
			"email_ids": [{"email_id": email, "is_primary": 1}],
			"links": [{"link_doctype": "Customer", "link_name": name}],
		}
		self.records[("Address", f"{name}-address")] = {
			"city": city,
			"country": "India",
			"links": [{"link_doctype": "Customer", "link_name": name}],
		}

	def fetch(self, doctype, name):
		record = self.records.get((doctype, name))
		return frappe._dict(record, name=name) if record is not None else None

	def find(self, doctype, filters, fields=None):
		if doctype == "Contact":
			return [frappe._dict(name=name) for name in self._contacts_with(filters[0][3])]
		return [
			frappe._dict(self.records[(doctype, name)], name=name)
			for name in self._linked(doctype, filters[1][3])
		]

	def _contacts_with(self, emails):
		for (doctype, name), record in self.records.items():
			if doctype == "Contact" and any(row["email_id"] in emails for row in record["email_ids"]):
				yield name

	def _linked(self, doctype, customer):
		for (dt, name), record in self.records.items():
			if dt == doctype and any(link["link_name"] == customer for link in record["links"]):
				yield name


@requires_accounting_system
class CustomerReuseTestCase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		complete_billing_profile(TEAM)
		self.enterContext(sync_mode())
		configure_accounting()
		self.enterContext(patch("central.billing.ingester.customer.has_billable_activity", return_value=True))
		self.remote = Remote()
		for fn in ("fetch", "find"):
			self.enterContext(patch(f"central.billing.ingester.connection.{fn}", getattr(self.remote, fn)))
		self.post = self.enterContext(patch(POST, return_value=frappe._dict(name="NEW-CUSTOMER")))
		self.put = self.enterContext(patch(PUT))

	def _step(self):
		return customer.take_next_step(frappe.get_doc("Billing Profile", TEAM))

	def _ids(self):
		return frappe.db.get_value("Billing Profile", TEAM, ["profile_id", "address_id", "contact_id"])


class TestFind(CustomerReuseTestCase):
	def test_the_matching_customer_is_used_with_its_address_and_contact(self):
		self.remote.add_customer("CUST-V1", customer_name=f"  {TEAM.upper()}   LTD ")

		self.assertEqual(self._step(), "update")

		self.assertEqual(self._ids(), ("CUST-V1", "CUST-V1-address", "CUST-V1-contact"))
		self.post.assert_not_called()
		self.assertTrue(
			frappe.db.exists("Billing Event", {"event_type": "Customer Reused", "reason": "CUST-V1"})
		)

	def test_a_customer_in_another_city_is_not_used(self):
		self.remote.add_customer("CUST-V1", city="Mumbai")
		self._step()
		self.assertEqual(self._ids()[0], "NEW-CUSTOMER")

	def test_two_matching_customers_are_left_to_an_operator(self):
		self.remote.add_customer("CUST-A")
		self.remote.add_customer("CUST-B")
		with self.assertRaises(frappe.ValidationError):
			self._step()
		self.post.assert_not_called()


class TestOperatorPick(CustomerReuseTestCase):
	def test_an_operator_picks_one_of_two(self):
		self.remote.add_customer("CUST-A")
		self.remote.add_customer("CUST-B")
		accounting.use_existing_customer(TEAM, "CUST-B")
		self.assertEqual(self._ids(), ("CUST-B", "CUST-B-address", "CUST-B-contact"))

	def test_a_customer_in_another_currency_is_refused(self):
		self.remote.add_customer("CUST-USD", currency="USD")
		with self.assertRaises(frappe.ValidationError):
			accounting.use_existing_customer(TEAM, "CUST-USD")
		self.assertEqual(self._ids(), (None, None, None))

	def test_only_an_operator_may_pick(self):
		self.remote.add_customer("CUST-A")
		frappe.set_user("Guest")
		self.addCleanup(frappe.set_user, "Administrator")
		with self.assertRaises(frappe.PermissionError):
			accounting.use_existing_customer(TEAM, "CUST-A")


class TestUpdateKeeps(CustomerReuseTestCase):
	def test_the_contact_keeps_its_other_emails_and_links(self):
		self.remote.add_customer("CUST-V1", email="old@test.example")
		contact = self.remote.records[("Contact", "CUST-V1-contact")]
		contact["links"].append({"link_doctype": "Lead", "link_name": "LEAD-1"})
		frappe.db.set_value(
			"Billing Profile",
			TEAM,
			{"profile_id": "CUST-V1", "address_id": "CUST-V1-address", "contact_id": "CUST-V1-contact"},
		)

		customer.update_customer_profile(frappe.get_doc("Billing Profile", TEAM))

		sent = next(call.args[1] for call in self.put.call_args_list if "Contact" in call.args[0])
		emails = [(row["email_id"], row["is_primary"]) for row in sent["email_ids"]]
		self.assertEqual(emails[0], ("old@test.example", 1))
		self.assertIn((EMAIL, 0), emails)
		self.assertEqual([link["link_name"] for link in sent["links"]], ["CUST-V1", "LEAD-1"])
