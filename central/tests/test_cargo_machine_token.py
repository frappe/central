import time
from unittest.mock import patch

import frappe
import jwt
from frappe.tests import IntegrationTestCase
from frappe.utils import set_request

from central.api.cargo import datum_token


class TestCargoMachineToken(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		self.region = self.registered_region(atlas_region_id="60117")
		self.mint = self.enterContext(patch("central.sso.mint_datum_token", return_value="datum-token"))

	def registered_region(self, atlas_region_id: str):
		region = frappe.get_doc(
			{
				"doctype": "Region",
				"region": frappe.generate_hash(length=8),
				"atlas_region_id": atlas_region_id,
				"status": "Active",
			}
		).insert()
		region.cargo_status = "Registered"
		region.cargo_webhook_secret = frappe.generate_hash(length=32)
		region.save()
		return region

	def machine_token(self, secret: str | None = None, **claims) -> str:
		payload = {
			"iss": "cargo",
			"aud": "central:datum-credential",
			"region": self.region.name,
			"machine": "vm-1",
			"role": "storage",
			"iat": int(time.time()),
			**claims,
		}
		return jwt.encode(payload, secret or self.region.get_password("cargo_webhook_secret"), "HS256")

	def call(self, token: str) -> dict:
		set_request(
			method="GET",
			path="/api/method/central.api.cargo.datum_token",
			headers={"X-Cargo-Machine-Token": token},
		)
		return datum_token()

	def test_a_signed_machine_token_gets_a_datum_token_for_that_machine(self):
		result = self.call(self.machine_token())

		self.assertEqual(result["token"], "datum-token")
		self.assertEqual(result["resource_id"], "cargo:vm-1")
		self.mint.assert_called_once_with(60117, "cargo:vm-1")

	def test_the_cargo_host_gets_a_datum_token_for_its_region(self):
		result = self.call(self.machine_token(role="cargo", machine=self.region.name))

		self.assertEqual(result["resource_id"], f"cargo:{self.region.name}")

	def test_a_token_signed_with_another_secret_is_refused(self):
		with self.assertRaises(frappe.AuthenticationError):
			self.call(self.machine_token(secret=frappe.generate_hash(length=32)))

	def test_a_token_naming_another_region_is_refused(self):
		"""One region's secret cannot vouch for a node in another region."""
		other = self.registered_region(atlas_region_id="60118")

		with self.assertRaises(frappe.AuthenticationError):
			self.call(self.machine_token(region=other.name))

		self.mint.assert_not_called()

	def test_a_region_whose_cargo_is_not_registered_is_refused(self):
		token = self.machine_token()
		self.region.db_set("cargo_status", "Disabled")

		with self.assertRaises(frappe.AuthenticationError):
			self.call(token)

	def test_a_token_for_another_audience_is_refused(self):
		with self.assertRaises(frappe.AuthenticationError):
			self.call(self.machine_token(aud="central:webhook"))

	def test_a_token_for_a_role_that_is_not_a_node_is_refused(self):
		with self.assertRaises(frappe.AuthenticationError):
			self.call(self.machine_token(role="builder"))
