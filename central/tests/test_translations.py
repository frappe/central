"""Copy a customer reads is translated when it is read, in the reader's language."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api.servers import _validate_firewall_change
from central.errors import build_envelope
from central.infrastructure.doctype.resource_action.resource_action import get_error
from central.notification.extractor import extract

GERMAN = {
	"The {action} didn't complete": "{action} wurde nicht abgeschlossen",
	"resize": "Größenänderung",
}


@contextmanager
def reading_in_german():
	"""Read as a German user, with GERMAN as the whole translation catalog."""
	language = frappe.local.lang
	frappe.local.lang = "de"
	try:
		with patch("frappe.translate.get_all_translations", return_value=GERMAN):
			yield
	finally:
		frappe.local.lang = language


class TestErrorTranslation(IntegrationTestCase):
	def test_an_envelope_is_built_in_the_readers_language(self):
		with reading_in_german():
			envelope = build_envelope("ACTION_FAILED", action="resize")

		self.assertEqual(envelope["title"], "Größenänderung wurde nicht abgeschlossen")

	def test_an_action_keeps_only_copy_the_catalog_cannot_rebuild(self):
		action = frappe.new_doc("Resource Action")
		action.action, action.resource_id = "resize", "vm-1"

		catalog = action._get_custom_copy(build_envelope("ACTION_FAILED", action="resize"))
		region = action._get_custom_copy(build_envelope("ACTION_FAILED", message="The disk is full."))

		self.assertEqual(catalog, {"error_message": None, "remediation": None})
		self.assertEqual(region["error_message"], "The disk is full.")
		self.assertIsNone(region["remediation"])

	def test_a_stored_error_is_read_in_the_readers_language(self):
		row = frappe._dict(
			error_code="ACTION_FAILED",
			action="resize",
			resource_id="vm-1",
			error_message=None,
			remediation=None,
		)

		with reading_in_german():
			self.assertEqual(get_error(row)["title"], "Größenänderung wurde nicht abgeschlossen")


class TestTranslationCatalog(IntegrationTestCase):
	def test_the_notification_fixture_copy_reaches_the_catalog(self):
		fixture = Path(frappe.get_app_path("central", "fixtures", "notification_event_type.json"))
		with fixture.open("rb") as file:
			messages = {message for _line, _function, message, _comments in extract(file)}

		self.assertIn("Payment failed", messages)
		self.assertIn("Payment for invoice {{ reference_name }} failed: {{ message }}", messages)


class TestFirewallErrors(IntegrationTestCase):
	def test_a_malformed_rule_names_the_field(self):
		change = {"inbound": [{"protocol": "nope", "ports": "", "cidrs": ["0.0.0.0/0"]}]}

		with self.assertRaisesRegex(frappe.ValidationError, "inbound.0.protocol"):
			_validate_firewall_change(change)
