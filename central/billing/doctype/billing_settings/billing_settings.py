# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Billing policy knobs, in one place.

These are the numbers the business changes without shipping code: what a new team
is granted, how long that grant lives, when an unpaid invoice is chased. They were
constants scattered across the billing modules; they are one Single now.

Read them through `central.billing.settings`, never off this document directly —
that module carries the fallback for a knob nobody has configured yet.
"""

import frappe
from frappe import _
from frappe.model.document import Document

# The last day that exists in every month.
LAST_SUSPENSION_DAY = 28


def validate_suspension_day(day: int | str | None) -> None:
	"""The suspension day is after the last payment day and exists in every month."""
	from central.billing.doctype.billing_profile.billing_profile import LAST_PAYMENT_DAY

	if not LAST_PAYMENT_DAY < frappe.utils.cint(day) <= LAST_SUSPENSION_DAY:
		frappe.throw(
			_("Suspension Day must be from the {0}th to the {1}th of the month.").format(
				LAST_PAYMENT_DAY + 1, LAST_SUSPENSION_DAY
			),
			title=_("Invalid Dunning Ladder"),
		)


class BillingSettings(Document):
	def onload(self):
		from central.billing.ingester.connection import enabled

		# The Accounting tab shows only while the accounting sync is on.
		self.set_onload("accounting_sync_enabled", enabled())

	def validate(self):
		self.strip_accounting_names()
		self.validate_dunning_ladder()
		self.validate_one_row_per_currency()
		self.validate_one_minimum_per_currency()
		self.validate_operator_alerts()

	@frappe.whitelist(methods=["POST"])
	def send_test_alert(self) -> list[str]:
		"""Send one test alert through the saved settings and return where it went."""
		from central.billing.platform.alerts import notify_operators

		alert = {
			"alert": "test",
			"doctype": self.doctype,
			"subject": self.name,
			"team": None,
			"detail": f"Test alert sent by {frappe.session.user}",
		}
		return notify_operators("Billing test alert", [alert])

	def alert_emails(self) -> list[str]:
		"""The operator alert addresses, one per line or comma separated."""
		raw = (self.operator_alert_emails or "").replace(",", "\n")
		return [email.strip() for email in raw.splitlines() if email.strip()]

	def validate_operator_alerts(self):
		"""Every address is valid, and a channel that includes Email has at least one."""
		emails = self.alert_emails()
		for email in emails:
			frappe.utils.validate_email_address(email, throw=True)
		if "Email" in self.operator_alert_channel and not emails:
			frappe.throw(
				_("Add at least one Alert Email Address, or set the Alert Channel to Raven."),
				title=_("Missing Alert Email Addresses"),
			)
		self.operator_alert_emails = "\n".join(emails)

	def strip_accounting_names(self):
		"""The accounting names are matched exactly, so a pasted space would miss."""
		for field in self.meta.get("fields", {"fieldtype": "Data"}):
			if isinstance(self.get(field.fieldname), str):
				self.set(field.fieldname, self.get(field.fieldname).strip())
		for row in self.gateways:
			for field in ("mode_of_payment", "clearing_account"):
				row.set(field, (row.get(field) or "").strip())

	def validate_dunning_ladder(self):
		"""Check the dunning ladder settings.

		1. Retries are at least 1 day apart.
		2. The suspension day is after the last payment day and exists in every month.
		3. Termination is due at least 1 day after suspension."""
		if frappe.utils.cint(self.dunning_retry_interval_days) < 1:
			frappe.throw(_("Retry Every must be at least 1 day."), title=_("Invalid Dunning Ladder"))
		validate_suspension_day(self.suspension_day)
		if frappe.utils.cint(self.terminate_after_days) < 1:
			frappe.throw(_("Terminate After must be at least 1 day."), title=_("Invalid Dunning Ladder"))

	def validate_one_minimum_per_currency(self):
		"""One minimum invoice amount per currency."""
		currencies = [row.currency for row in self.minimum_invoice_amounts]
		if len(currencies) != len(set(currencies)):
			frappe.throw(
				_("Each currency can have one minimum invoice amount."), title=_("Duplicate Currency")
			)

	def validate_one_row_per_currency(self):
		"""One grant amount per currency — two rows would make the grant ambiguous."""
		seen = set()
		for row in self.welcome_credit_amounts:
			if row.currency in seen:
				frappe.throw(
					_("Row {0}: {1} already has a welcome credit amount.").format(row.idx, row.currency),
					title=_("Duplicate Currency"),
				)
			seen.add(row.currency)
