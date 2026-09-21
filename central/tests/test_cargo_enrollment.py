import json
from unittest.mock import patch

import frappe
import requests
from frappe.tests import IntegrationTestCase

from central.errors import AtlasConnectionError, CargoConnectionError


class TestCargoEnrollment(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		self.instance = frappe.get_doc(
			{
				"doctype": "Region",
				"region": frappe.generate_hash(length=8),
				"atlas_region_id": "7",
				"cargo_base_url": "http://cargo.example.test:8000",
				"status": "Active",
			}
		).insert()
		self.token = self.enterContext(
			patch("central.integrations.cargo.mint_cargo_token", return_value="test-cargo-token")
		)
		self.get = self.enterContext(patch("central.integrations.cargo.requests.get"))
		self.post = self.enterContext(patch("central.integrations.cargo.requests.post"))
		self.get.return_value = self.response({"message": "pong"})
		self.post.return_value = self.response({"request_url": "...", "enabled": True})

	def response(self, body, status=200):
		response = requests.Response()
		response.status_code = status
		response._content = json.dumps(body).encode()
		return response

	def test_enroll_registers_once_cargo_answers(self):
		self.instance.enroll_cargo()

		self.get.assert_called_once_with("http://cargo.example.test:8000/api/method/ping", timeout=(5, 10))
		headers = self.post.call_args.kwargs["headers"]
		self.assertEqual(headers["X-Cargo-Access-Token"], "test-cargo-token")
		self.token.assert_called_once_with(7)

		self.instance.reload()
		self.assertEqual(self.instance.cargo_status, "Registered")
		self.assertIsNotNone(self.instance.cargo_registered_at)
		secret = self.instance.get_password("cargo_webhook_secret")
		self.assertTrue(secret)
		self.assertEqual(self.post.call_args.kwargs["json"]["webhook_secret"], secret)

	def test_enroll_raises_when_cargo_has_not_answered_yet(self):
		self.get.return_value = self.response({}, 503)

		with self.assertRaises(CargoConnectionError):
			self.instance.enroll_cargo()

		self.post.assert_not_called()
		self.assertEqual(self.instance.reload().cargo_status, "Draft")

	def test_enroll_raises_on_a_rejected_configuration_and_persists_nothing(self):
		self.post.return_value = self.response({}, 403)

		with self.assertRaises(CargoConnectionError):
			self.instance.enroll_cargo()

		self.instance.reload()
		self.assertEqual(self.instance.cargo_status, "Draft")
		self.assertIsNone(self.instance.get_password("cargo_webhook_secret", raise_exception=False))

	def test_enroll_without_an_atlas_region_id_raises_instead_of_registering(self):
		self.instance.db_set("atlas_region_id", None)

		with self.assertRaises(AtlasConnectionError):
			self.instance.enroll_cargo()

		self.post.assert_not_called()
		self.assertEqual(self.instance.reload().cargo_status, "Draft")

	def test_enroll_is_operator_only(self):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": f"regional-{frappe.generate_hash(length=8)}@example.test",
				"first_name": "Regional test",
				"send_welcome_email": 0,
				"roles": [{"role": "Central User"}],
			}
		).insert()
		frappe.set_user(user.name)
		self.addCleanup(frappe.set_user, "Administrator")

		with self.assertRaises(frappe.PermissionError):
			self.instance.enroll_cargo()
		self.get.assert_not_called()
