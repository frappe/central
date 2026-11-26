"""Every notification email renders with real values, and every link goes somewhere."""

import json
from pathlib import Path
from typing import ClassVar

import frappe
from frappe.tests import IntegrationTestCase

from central.notification.engine import _render_template, render_notification_email

FIXTURE = Path(frappe.get_app_path("central", "fixtures", "notification_event_type.json"))

ROUTE_PREFIXES = ("/servers", "/billing", "/team", "/settings", "/llm", "/signup", "/object-storage")

SAMPLE_CONTEXT: dict = {
	"product": "Frappe Cloud",
	"product_key": "press",
	"address": "acme.frappe.cloud",
	"ends_on": "20 Nov 2026",
	"deletes_on": "4 Dec 2026",
	"days_left": 3,
	"paid_invoice": "INV-0002",
	"amount": "₹1,180.00",
	"method": "Visa ending 4242",
	"tax_note": "incl. IGST 18%",
	"tax_label": "IGST 18%",
	"invoice": "INV-0001",
	"charge_on": "20 Nov 2026",
	"total": "₹1,180.00",
	"credit_applied": "₹100.00",
	"payment_date": "20 Nov 2026",
	"pays_by_hand": True,
	"over_limit": False,
	"limit": "₹15,000.00",
	"limit_tax_note": "incl. IGST 18%",
	"amount_with_gst": "₹1,180.00",
	"held": True,
	"includes_earlier_gst": False,
	"topup": "1000",
	"payment_day": "5th",
	"next_payment_date": "5 Dec 2026",
	"open_invoice": "INV-0001",
	"open_payment_date": "20 Nov 2026",
	"title": "web-prod-01",
	"action": "resize",
	"member": "Ada Lovelace",
	"domains": ["acme.frappe.cloud", "www.acme.example"],
	"bench": "bench-01",
	"app": "octo/app",
	"sites": [
		{"site": "acme.frappe.cloud", "status_code": 500, "response_ms": 1230, "error": None},
	],
}


def fixture_events() -> list[frappe._dict]:
	with FIXTURE.open() as file:
		return [frappe._dict(row) for row in json.load(file)]


def sample_reader_context(**overrides) -> dict:
	"""The context dispatch builds, with a value for every template variable."""
	return {
		"team": "",
		"team_name": "Acme",
		"reference_name": "acme.frappe.cloud",
		"reference_doctype": "Site",
		"reference_title": "acme.frappe.cloud",
		"server": "vm-1",
		"server_title": "web-prod-01",
		"message": "probe timed out",
		"context": dict(SAMPLE_CONTEXT),
		**overrides,
	}


class TestEventCopy(IntegrationTestCase):
	_events: ClassVar[list[frappe._dict] | None] = None

	def events(self) -> list[frappe._dict]:
		if self.__class__._events is None:
			self.__class__._events = fixture_events()
		return self.__class__._events

	def test_every_event_renders_with_no_template_error(self):
		for event in self.events():
			subject, html = render_notification_email(event, sample_reader_context(), {})

			with self.subTest(event=event.name):
				self.assertTrue(subject)
				for text in (subject, html):
					self.assertNotIn("no such element", text)
					self.assertNotIn("{{", text)

	def test_a_button_has_a_label_and_a_console_route(self):
		for event in self.events():
			with self.subTest(event=event.name):
				if event.action_route:
					self.assertTrue(event.action_label)
					self.assertTrue(
						event.action_route.startswith(ROUTE_PREFIXES),
						f"{event.name} links to {event.action_route}, which the console does not serve",
					)
				else:
					self.assertFalse(event.action_label)


class TestSiteAlertDetail(IntegrationTestCase):
	def event(self) -> frappe._dict:
		return frappe._dict(next(row for row in fixture_events() if row["name"] == "site_unavailable"))

	def render(self, ctx: dict) -> str:
		return _render_template(self.event().in_app_body, ctx) or ""

	def test_the_body_names_the_probe_result(self):
		down = {"site": "acme.frappe.cloud", "status_code": 500, "response_ms": 1200, "error": None}
		cases = (
			([down], "acme.frappe.cloud returned HTTP 500."),
			(
				[{**down, "status_code": None, "error": "timed out"}],
				"acme.frappe.cloud did not respond (timed out).",
			),
			(
				[down, {**down, "site": "beta.frappe.cloud", "status_code": None}],
				"acme.frappe.cloud returned HTTP 500; beta.frappe.cloud did not respond.",
			),
			(None, "acme.frappe.cloud did not respond to its health check."),
		)
		for sites, expected in cases:
			ctx = sample_reader_context()
			if sites is None:
				del ctx["context"]
			else:
				ctx["context"]["sites"] = sites

			with self.subTest(expected=expected):
				self.assertEqual(self.render(ctx), expected)
