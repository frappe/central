# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Re-issuing a period's invoices after a price was found to be wrong.

Correcting the price is not this module's job — a catalog rate or a rollup's locked
terms is fixed first. This is what happens next: find who was billed on the old price,
show what changing it would do, and re-issue them.

Nothing here edits an issued invoice. A correction is always cancel-and-reissue, so
what a customer was told and what they were told next both survive.
"""

import frappe

from central.billing.revenue.invoicing.lifecycle import reissue_invoice

# Statuses a correction may touch. A Paid invoice is money already taken and is a
# refund's problem, not a reissue's.
CORRECTABLE = ("Draft", "Open", "Overdue")


def affected_invoices(resource_type: str, period_start, period_end) -> list[str]:
	"""Correctable invoices in the period carrying a line for this resource type."""
	invoice = frappe.qb.DocType("Invoice")
	item = frappe.qb.DocType("Invoice Line Item")
	return (
		frappe.qb.from_(invoice)
		.join(item)
		.on(item.parent == invoice.name)
		.select(invoice.name)
		.distinct()
		.where(item.resource_type == resource_type)
		.where(invoice.status.isin(CORRECTABLE))
		.where(invoice.period_start >= frappe.utils.getdate(period_start))
		.where(invoice.period_end <= frappe.utils.getdate(period_end))
		.orderby(invoice.name)
	).run(pluck=True)


def preview(resource_type: str, period_start, period_end) -> dict:
	"""What re-issuing would change, without changing anything.

	The new total is what the invoice would be rated at today, so it already reflects
	whatever correction was made to the price.
	"""
	rows = []
	for name in affected_invoices(resource_type, period_start, period_end):
		inv = frappe.get_doc("Invoice", name)
		rows.append(
			{
				"invoice": name,
				"team": inv.team,
				"currency": inv.currency,
				"old_total": frappe.utils.flt(inv.total),
				"new_total": _rated_today(inv),
			}
		)
	for row in rows:
		row["delta"] = frappe.utils.flt(row["new_total"] - row["old_total"], 2)
	return {
		"resource_type": resource_type,
		"period_start": str(period_start),
		"period_end": str(period_end),
		"invoices": rows,
		"changed": sum(1 for r in rows if r["delta"]),
		"net_delta": frappe.utils.flt(sum(r["delta"] for r in rows), 2),
	}


def _rated_today(invoice) -> float:
	"""What this invoice's period would total if it were rated now."""
	from central.billing.revenue.invoicing.lines import team_line_items
	from central.billing.revenue.metering import metered_line_items_for_clusters

	clusters = frappe.get_all(
		"Subscription", filters={"team": invoice.team}, pluck="cluster", distinct=True
	)
	lines = team_line_items(invoice.team, invoice.period_start, invoice.period_end)
	lines += metered_line_items_for_clusters(
		invoice.team, [c for c in clusters if c], invoice.period_start, invoice.period_end
	)
	return frappe.utils.flt(sum(frappe.utils.flt(line.get("amount")) for line in lines), 2)


def apply(resource_type: str, period_start, period_end, reason: str) -> str:
	"""Re-issue every affected invoice, and record what was done.

	One invoice at a time, committed as it goes: a correction that fails half way
	through leaves the invoices it already re-issued correct, and the run says so.
	"""
	plan = preview(resource_type, period_start, period_end)
	run = frappe.get_doc(
		{
			"doctype": "Rerating Run",
			"resource_type": resource_type,
			"period_start": period_start,
			"period_end": period_end,
			"reason": reason,
			"status": "Running",
			"invoices_affected": len(plan["invoices"]),
			"net_delta": plan["net_delta"],
			"preview": frappe.as_json(plan["invoices"], indent=1),
		}
	).insert(ignore_permissions=True)

	reissued, failed = [], []
	for row in plan["invoices"]:
		try:
			new = reissue_invoice(row["invoice"], reason=f"Re-rated: {reason}")
			reissued.append({"from": row["invoice"], "to": new, "delta": row["delta"]})
		except Exception as error:
			failed.append({"invoice": row["invoice"], "error": str(error)})
			frappe.log_error(
				title=f"Re-rating failed for {row['invoice']}", message=frappe.get_traceback()
			)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- one invoice, one transaction

	run.reload()
	run.reissued = len(reissued)
	run.failed = len(failed)
	run.result = frappe.as_json({"reissued": reissued, "failed": failed}, indent=1)
	run.finish("Failed" if failed and not reissued else "Complete")
	return run.name
