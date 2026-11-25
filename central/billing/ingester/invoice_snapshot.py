# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The two fields a Sales Invoice on frappe.io carries for Frappe Cloud.

`frappe_cloud_invoice_id` is the Central invoice name; the sync also finds its Sales Invoice by
it. `frappe_cloud_invoice` is the invoice as JSON, in the shape Press v1 sent. The print format
the customer gets reads its lines, billing period and applied credit from it, so a key it reads
is never left out or null.
"""

import json

import frappe

FIELDS = ("frappe_cloud_invoice_id", "frappe_cloud_invoice")


def invoice_fields(inv, promotional: float) -> dict:
	"""For the Sales Invoice of `inv`. `promotional` is the credit the Sales Invoice leaves out."""
	snapshot = {
		**_header(inv, "Subscription"),
		"status": inv.status,
		"period_start": inv.period_start,
		"total": frappe.utils.flt(inv.total),
		"amount_paid": frappe.utils.flt(inv.amount_paid),
		"tds_amount": frappe.utils.flt(inv.tds_amount),
		# Lines less this is the Sales Invoice's total, as the print format shows it.
		"applied_credits": frappe.utils.flt(promotional, 2),
		"items": [_line(line) for line in inv.items],
	}
	return _fields(inv.name, snapshot)


def refund_fields(inv, refund: str, description: str, amount: float) -> dict:
	"""For a credit note of `inv`: one line for what `refund` gives back."""
	snapshot = {
		**_header(inv, "Refund"),
		"refund": refund,
		"applied_credits": 0,
		"items": [
			{
				"document_name": inv.name,
				"plan": "",
				"description": description,
				"rate": frappe.utils.flt(amount),
				"quantity": 1,
				"amount": frappe.utils.flt(amount),
			}
		],
	}
	return _fields(inv.name, snapshot)


def _header(inv, kind: str) -> dict:
	return {
		"name": inv.name,
		"team": inv.team,
		"currency": inv.currency,
		"type": kind,
		"period_end": inv.period_end,
		"due_date": inv.due_date or inv.period_end,
	}


def _line(line) -> dict:
	return {
		"document_name": line.subscription_resource or line.project_title or line.resource_type or "",
		"plan": line.plan or "",
		"description": line.description or line.plan or "",
		"rate": frappe.utils.flt(line.rate),
		"quantity": frappe.utils.flt(line.quantity) or 1,
		"amount": frappe.utils.flt(line.amount),
	}


def _fields(name: str, snapshot: dict) -> dict:
	return {
		"frappe_cloud_invoice_id": name,
		"frappe_cloud_invoice": json.dumps(snapshot, indent=4, sort_keys=True, default=str),
	}
