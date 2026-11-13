# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""What a wallet pays of a bill, worked out without writing anything.

The collector spends this draw, and the top-up ask reads it to know how much purchased
credit a bill still needs.
"""

import frappe

# What is left owed below this is treated as paid.
PAID_TOLERANCE = 0.005


def plan_draw(lots: list, collectable: float, gst_due: float, gst_left: float) -> frappe._dict:
	"""What `lots` pay of `collectable`, of which `gst_due` is GST, in the order they are spent.

	Credit with GST already paid on it (a top-up) pays the bill's net amount, and that GST
	(`gst_left` in all) pays the GST on it. Any other credit (promotional, a refund) pays
	the bill as it stands, GST included. `owed` is what the card or UPI is left with, and
	`gst_spare` the top-up GST this draw did not use."""
	gst_per_net = get_gst_per_net(collectable, gst_due)
	owed, wallet, advance, gst = collectable, 0.0, 0.0, 0.0
	for lot in lots:
		if owed <= PAID_TOLERANCE:
			break
		if lot.remaining <= 0:
			continue
		if lot.paid_in and gst_per_net:
			net = min(lot.remaining, owed / (1 + gst_per_net))
			tax = min(net * gst_per_net, max(gst_left - gst, 0))
			wallet, advance, gst, owed = wallet + net, advance + net, gst + tax, owed - net - tax
		else:
			use = min(lot.remaining, owed)
			wallet, owed = wallet + use, owed - use
			if lot.paid_in:
				advance += use
	return frappe._dict(
		wallet=frappe.utils.flt(wallet, 2),
		advance=frappe.utils.flt(advance, 2),
		gst=frappe.utils.flt(gst, 2),
		owed=max(owed, 0.0),
		gst_spare=max(gst_left - gst, 0.0),
	)


def credit_to_cover(draw: frappe._dict, collectable: float, gst_due: float, top_up_rate: float) -> float:
	"""Purchased credit that, spent after the wallet in `draw`, pays what it left owed.

	New credit never expires and is the newest, so it is spent last. With GST on the bill it
	pays the net, and its own GST (`top_up_rate`) with what GST is spare pays the GST."""
	owed = draw.owed
	if frappe.utils.flt(owed, 2) <= 0:
		return 0.0
	gst_per_net = get_gst_per_net(collectable, gst_due)
	return max(owed / (1 + gst_per_net), (owed - draw.gst_spare) / (1 + top_up_rate))


def gst_still_due(doc, due: float) -> float:
	"""The GST share of what is still due. Earlier credit paid GST in proportion to what it paid."""
	collectable = frappe.utils.flt(doc.total) - frappe.utils.flt(doc.tds_amount)
	if collectable <= 0:
		return 0.0
	return frappe.utils.flt(doc.output_tax_amount) * due / collectable


def get_gst_per_net(collectable: float, gst_due: float) -> float:
	net_due = collectable - gst_due
	return gst_due / net_due if gst_due and net_due > 0 else 0
