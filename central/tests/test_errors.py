"""The server-flow error envelope: known failures become clean, structured messages,
and no action ever reaches the user as a bare exception or raw traceback."""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.errors import (
	ENVELOPE_KEY,
	ERROR_CATALOG,
	ServerActionError,
	build_envelope,
	server_action,
	throw_action_error,
	to_error_response,
)


class TestErrorCatalog(IntegrationTestCase):
	def test_every_catalog_entry_is_complete(self):
		for code, entry in ERROR_CATALOG.items():
			for key in ("title", "message", "remediation", "retriable"):
				self.assertIn(key, entry, f"{code} missing {key}")

	def test_build_envelope_fills_context_and_keeps_shape(self):
		env = build_envelope("SERVER_NOT_FOUND", resource_id="vm-9")
		self.assertEqual(env["code"], "SERVER_NOT_FOUND")
		self.assertIn("vm-9", env["message"])
		self.assertFalse(env["retriable"])
		self.assertTrue(env["title"])

	def test_missing_placeholder_renders_empty_not_crash(self):
		env = build_envelope("SERVER_NOT_FOUND")
		self.assertEqual(env["code"], "SERVER_NOT_FOUND")

	def test_message_override_wins(self):
		env = build_envelope("ATLAS_REJECTED", message="No capacity — retry shortly.", action="create this server")
		self.assertEqual(env["message"], "No capacity — retry shortly.")
		self.assertIn("create this server", env["title"])

	def test_unknown_code_falls_back_to_unexpected(self):
		self.assertEqual(build_envelope("NOPE")["code"], "UNEXPECTED")


class TestThrowActionError(IntegrationTestCase):
	def setUp(self):
		frappe.clear_messages()

	def test_carries_envelope_on_the_message_log(self):
		with self.assertRaises(ServerActionError) as caught:
			throw_action_error("SERVER_BUSY_RESIZING", action="start")
		self.assertEqual(caught.exception.envelope["code"], "SERVER_BUSY_RESIZING")
		self.assertEqual(frappe.message_log[-1][ENVELOPE_KEY]["code"], "SERVER_BUSY_RESIZING")

	def test_exc_override_keeps_the_status_type(self):
		with self.assertRaises(frappe.PermissionError):
			throw_action_error("PERMISSION_DENIED", exc=frappe.PermissionError, action="terminate")


class TestToErrorResponse(IntegrationTestCase):
	def test_preserves_a_user_facing_validation_message(self):
		env = to_error_response(frappe.ValidationError("Disk can't shrink below 40 GB."))
		self.assertEqual(env["code"], "VALIDATION_ERROR")
		self.assertIn("shrink", env["message"])

	def test_permission_maps_to_permission_denied(self):
		self.assertEqual(to_error_response(frappe.PermissionError("nope"))["code"], "PERMISSION_DENIED")

	def test_unexpected_error_is_logged_and_generalised(self):
		with patch("central.errors.frappe.log_error") as log:
			env = to_error_response(KeyError("internal detail"))
		self.assertEqual(env["code"], "UNEXPECTED")
		self.assertNotIn("internal detail", env["message"])
		log.assert_called_once()

	def test_prebuilt_envelope_passes_through(self):
		error = ServerActionError("x")
		error.envelope = {"code": "ATLAS_REJECTED"}
		self.assertEqual(to_error_response(error)["code"], "ATLAS_REJECTED")


class TestServerActionDecorator(IntegrationTestCase):
	def setUp(self):
		frappe.clear_messages()

	def test_unexpected_exception_becomes_a_clean_envelope(self):
		@server_action
		def boom():
			raise KeyError("internal detail")

		with patch("central.errors.frappe.log_error"):
			with self.assertRaises(ServerActionError) as caught:
				boom()
		self.assertEqual(caught.exception.envelope["code"], "UNEXPECTED")
		# The raw exception text must never surface to the user.
		self.assertNotIn("internal detail", caught.exception.envelope["message"])

	def test_clean_validation_error_passes_through_enriched(self):
		@server_action
		def bad():
			frappe.throw("Region is required.", frappe.ValidationError)

		with self.assertRaises(frappe.ValidationError) as caught:
			bad()
		self.assertEqual(caught.exception.envelope["code"], "VALIDATION_ERROR")
		self.assertIn("Region is required", str(caught.exception))

	def test_prebuilt_error_is_not_reprocessed(self):
		@server_action
		def rejected():
			throw_action_error("ATLAS_REJECTED", message="No capacity.", action="create this server")

		with self.assertRaises(ServerActionError) as caught:
			rejected()
		self.assertEqual(caught.exception.envelope["message"], "No capacity.")
