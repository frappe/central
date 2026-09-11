"""The gate on reports Cargo sends Central: Frappe's own webhook signature, checked
against the secret the provisioner gave both sides. get_request_header is patched, no
live HTTP."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils.password import remove_encrypted_password, set_encrypted_password

from central.integrations import cargo_webhook as cargo_module
from central.integrations.cargo_webhook import (
	_authenticate_cargo_webhook,
	signature_matches,
	verify_cargo_webhook,
)
from central.tests.utils import ensure_region

REGION = "cargo-webhook"
SECRET = "shared-with-the-host"
BODY = json.dumps({"region": REGION, "region_id": 3, "service": "storage", "status": "Active"}).encode()

# --- Golden vector: pinned to what frappe.integrations.doctype.webhook signs with. A
# format change on either side leaves both suites green while every real report is
# rejected. Do not regenerate the digest to make a test pass.
GOLDEN_SECRET = "cargo-golden-secret"
GOLDEN_BODY = b'{"region": "blr", "service": "storage", "status": "Active"}'
GOLDEN_SIGNATURE = "2x+jVtEYhGsQJZ9a1CAA1QKPY6mA0lVlLgNb1v1goFc="


def ensure_cargo_instance(region: str):
	"""The host for one region. Kept, not remade: these rows outlive a single test."""
	ensure_region(region)
	name = frappe.db.get_value("Cargo Instance", {"region": region})
	if name:
		instance = frappe.get_doc("Cargo Instance", name)
		instance.db_set("status", "Draft")
		return instance

	return frappe.get_doc({"doctype": "Cargo Instance", "region": region}).insert(ignore_permissions=True)


def sign(body: bytes, secret: str = SECRET) -> str:
	return base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()


class IntegrationTestCargoWebhookSignature(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.instance = ensure_cargo_instance(REGION)
		set_encrypted_password("Cargo Instance", self.instance.name, SECRET, "webhook_secret")

	@contextmanager
	def signed(self, signature: str | None = None, body: bytes = BODY):
		"""One inbound report, signed validly unless the test says otherwise."""
		header = signature if signature is not None else sign(body)
		with patch.object(cargo_module.frappe, "get_request_header", return_value=header):
			yield body

	def test_a_report_signed_with_the_shared_secret_is_the_hosts_own(self):
		with self.signed() as body:
			verified = _authenticate_cargo_webhook(body)

		self.assertEqual(verified.instance, self.instance.name)
		self.assertEqual(verified.region, REGION)

	def test_a_report_signed_with_another_secret_is_refused(self):
		with self.signed(signature=sign(BODY, "not-the-secret")) as body:
			with self.assertRaises(frappe.PermissionError):
				_authenticate_cargo_webhook(body)

	def test_a_body_changed_after_signing_is_refused(self):
		"""The signature covers the payload, which is the point of signing over sending."""
		with self.signed():
			tampered = BODY.replace(b'"Active"', b'"Failed"')
			with self.assertRaises(frappe.PermissionError):
				_authenticate_cargo_webhook(tampered)

	def test_a_report_carrying_no_signature_is_refused(self):
		with self.signed(signature=""):
			with self.assertRaises(frappe.PermissionError):
				_authenticate_cargo_webhook(BODY)

	def test_a_region_central_does_not_know_is_refused(self):
		body = BODY.replace(REGION.encode(), b"somewhere-else")
		# Signed correctly: the region picks the secret, it does not stand in for one.
		with self.signed(signature=sign(body), body=body):
			with self.assertRaises(frappe.PermissionError):
				_authenticate_cargo_webhook(body)

	def test_a_disabled_host_is_refused(self):
		self.instance.db_set("status", "Disabled")

		with self.signed() as body:
			with self.assertRaises(frappe.PermissionError):
				_authenticate_cargo_webhook(body)

	def test_a_host_with_no_secret_recorded_is_refused(self):
		other = "cargo-webhook-secretless"
		remove_encrypted_password("Cargo Instance", ensure_cargo_instance(other).name, "webhook_secret")
		body = BODY.replace(REGION.encode(), other.encode())

		with self.signed(signature=sign(body), body=body):
			with self.assertRaises(frappe.PermissionError):
				_authenticate_cargo_webhook(body)

	def test_a_body_that_is_not_a_report_is_refused(self):
		with self.signed(signature=sign(b"not json"), body=b"not json"):
			with self.assertRaises(frappe.PermissionError):
				_authenticate_cargo_webhook(b"not json")

	def test_the_decorator_leaves_the_verified_host_behind(self):
		@verify_cargo_webhook
		def handler():
			return "ran"

		with self.signed() as body:
			with patch.object(cargo_module.frappe, "request", frappe._dict(get_data=lambda: body)):
				self.assertEqual(handler(), "ran")

		self.assertEqual(frappe.local.cargo_webhook.instance, self.instance.name)


class UnitTestGoldenVector(IntegrationTestCase):
	"""Pin the verifier to the wire contract, independently of request plumbing."""

	def test_the_verifier_accepts_the_golden_signature(self):
		self.assertTrue(signature_matches(GOLDEN_SECRET, GOLDEN_BODY, GOLDEN_SIGNATURE))

	def test_the_golden_signature_covers_the_body(self):
		self.assertFalse(signature_matches(GOLDEN_SECRET, GOLDEN_BODY + b" ", GOLDEN_SIGNATURE))
