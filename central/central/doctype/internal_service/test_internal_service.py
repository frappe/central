# Copyright (c) 2026, frappe and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from central.central.doctype.internal_service.internal_service import InternalService
from central.tests.utils import ensure_region

EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = []


class IntegrationTestInternalService(IntegrationTestCase):
	"""One row per service per region, named after both."""

	def setUp(self):
		frappe.set_user("Administrator")
		# One region per test: the row name is derived from it, so a shared one collides.
		self.region = ensure_region(f"test-fold-{frappe.generate_hash(length=8)}")

	def service(self, service_type: str, base_url: str = "") -> InternalService:
		return frappe.get_doc(
			{
				"doctype": "Internal Service",
				"region": self.region,
				"service_type": service_type,
				"base_url": base_url,
			}
		).insert(ignore_permissions=True)

	def test_the_name_carries_the_service_and_the_region(self):
		"""A Cargo token's `instance` claim is this name, so the format is load-bearing."""
		self.assertEqual(self.service("Cargo").name, f"CARGO-{self.region}")
		self.assertEqual(self.service("Datum").name, f"DATUM-{self.region}")

	def test_one_row_per_service_per_region(self):
		self.service("Datum")
		with self.assertRaises(frappe.DuplicateEntryError):
			self.service("Datum")

	def test_a_trailing_slash_is_dropped(self):
		service = self.service("Datum", f"https://{self.region}.datum.frappe.cloud/")
		self.assertEqual(service.base_url, f"https://{self.region}.datum.frappe.cloud")

	def test_url_for_returns_the_base_url(self):
		self.service("Datum", f"https://{self.region}.datum.frappe.cloud")
		self.assertEqual(
			InternalService.url_for(self.region, "Datum"), f"https://{self.region}.datum.frappe.cloud"
		)

	def test_url_for_throws_when_nothing_is_recorded(self):
		with self.assertRaises(frappe.ValidationError):
			InternalService.url_for(self.region, "Datum")

	def test_a_disabled_service_is_not_reachable(self):
		service = self.service("Datum", f"https://{self.region}.datum.frappe.cloud")
		service.db_set("status", "Disabled")
		with self.assertRaises(frappe.ValidationError):
			InternalService.url_for(self.region, "Datum")

	def test_datum_can_be_issued_a_bootstrapping_token(self):
		"""Enrolment is one handshake: the scope no longer names Cargo."""
		from central.sso import SERVICE_BOOTSTRAPPING_SCOPE, verify_service_bootstrapping_token

		service = self.service("Datum")
		token = service.issue_bootstrapping_token()["bootstrapping_token"]

		self.assertEqual(verify_service_bootstrapping_token(token), service.name)
		self.assertTrue(SERVICE_BOOTSTRAPPING_SCOPE)
