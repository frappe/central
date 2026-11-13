# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""What a wallet pays of a bill, worked out without writing anything.

The collector spends this draw, and the top-up ask reads it to know how much purchased
credit a bill still needs.
"""

import math

import frappe

# What is left owed below this is treated as paid.
PAID_TOLERANCE = 0.005


def plan_draw(lots: list, collectable: float, gst_due: float, gst_left: float) -> frappe._dict:
	"""What `lots` pay of `collectable`, of which `gst_due` is GST, in the order they are spent.

	Credit with GST already paid on it (a top-up) pays the bill's net amount, and that GST
	(`gst_left` in all) pays the GST on it. Any other credit (promotional, a refund) pays
	the bill as it stands, GST included. `owed` is what the card or UPI is left with,
	`gst_spare` the top-up GST this draw did not use, and `gst_unpaid` the GST its top-up
	lots needed that `gst_left` did not have."""
	gst_per_net = get_gst_per_net(collectable, gst_due)
	owed, wallet, advance, gst, gst_needed = collectable, 0.0, 0.0, 0.0, 0.0
	for lot in lots:
		if owed <= PAID_TOLERANCE:
			break
		if lot.remaining <= 0:
			continue
		if lot.paid_in and gst_per_net:
			net = min(lot.remaining, owed / (1 + gst_per_net))
			gst_needed += net * gst_per_net
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
		gst_unpaid=max(frappe.utils.flt(gst_needed - gst, 2), 0.0),
	)


# The cover formula can miss by a rounding step; a larger gap means the inputs disagree.
MAX_EXTRA_STEPS = 3


class TopUpAsk:
	"""The least purchased credit, in whole steps, that makes the wallet pay all of a bill.

	The cover formula gives a credit that always pays (one step more when the 2-dp rounding
	of the draw misses by 0.01). It can be more than needed: when the GST left is short,
	older top-ups pay less and promotional credit more. So the steps below it are searched
	with the collector's own draw."""

	def __init__(self, lots: list, collectable: float, gst_due: float, gst_left: float, top_up_rate: float):
		self.lots, self.collectable, self.gst_due = lots, collectable, gst_due
		self.gst_left, self.top_up_rate = gst_left, top_up_rate

	def credit(self, step: int) -> int | None:
		draw = plan_draw(self.lots, self.collectable, self.gst_due, self.gst_left)
		cover = credit_to_cover(draw, self.collectable, self.gst_due, self.top_up_rate)
		pays = math.ceil(frappe.utils.flt(cover, 2) / step)
		if not pays:
			return 0
		pays = self._first_paying(pays, step)
		if pays is None:
			return None
		short = 0
		while pays - short > 1:
			mid = (pays + short) // 2
			pays, short = (mid, short) if self.is_paid_with(mid * step) else (pays, mid)
		return pays * step

	def _first_paying(self, pays: int, step: int) -> int | None:
		"""The first step from `pays` that pays the bill, a few steps up at most, or None
		when none does (the bill's GST and the top-up GST disagree)."""
		for extra in range(MAX_EXTRA_STEPS + 1):
			if self.is_paid_with((pays + extra) * step):
				return pays + extra
		return None

	def is_paid_with(self, credit: float) -> bool:
		"""Whether the wallet pays the bill once `credit`, with its GST, is added last."""
		top_up = frappe._dict(remaining=credit, paid_in=1)
		gst_left = self.gst_left + frappe.utils.flt(credit * self.top_up_rate, 2)
		draw = plan_draw([*self.lots, top_up], self.collectable, self.gst_due, gst_left)
		return is_paid_by(draw, self.collectable)


def credit_to_cover(draw: frappe._dict, collectable: float, gst_due: float, top_up_rate: float) -> float:
	"""Purchased credit that, spent after the wallet in `draw`, pays what it left owed.

	New credit never expires, so it is spent last. Purchased credit pays the bill's net and
	top-up GST pays its GST, so all purchased credit together must reach the net of what it
	pays, and all top-up GST the GST of that. Older lots use the new GST first."""
	if frappe.utils.flt(draw.owed, 2) <= 0:
		return 0.0
	gross = draw.owed + draw.advance + draw.gst
	net = gross / (1 + get_gst_per_net(collectable, gst_due))
	needed = net - draw.advance
	if top_up_rate:
		needed = max(needed, (gross - net - draw.gst - draw.gst_spare) / top_up_rate)
	return needed


def is_paid_by(draw: frappe._dict, collectable: float) -> bool:
	"""Whether `draw` pays all of `collectable`, as the collector rounds it."""
	return draw.wallet > 0 and frappe.utils.flt(collectable - draw.wallet - draw.gst, 2) <= 0


def gst_still_due(doc, due: float) -> float:
	"""The GST share of what is still due. Earlier credit paid GST in proportion to what it paid."""
	collectable = frappe.utils.flt(doc.total) - frappe.utils.flt(doc.tds_amount)
	if collectable <= 0:
		return 0.0
	return frappe.utils.flt(doc.output_tax_amount) * due / collectable


def get_gst_per_net(collectable: float, gst_due: float) -> float:
	net_due = collectable - gst_due
	return gst_due / net_due if gst_due and net_due > 0 else 0
