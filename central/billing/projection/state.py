# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""A team's billing state, seeded once and then advanced in memory.

Projecting six months is not six independent projections. Month two is downstream of
month one: the wallet was drawn, an invoice went overdue, standing moved to past due,
a suspension stopped accrual mid-month, a settled invoice promoted the trust tier and
with it the spend cap. Answering each month from the live database would refill the
wallet every time and report a team as comfortable right up to the point it is cut off.

So the database is read **once**, at t0, and everything after that is arithmetic. This
object is what the evolving-state readers consult through their `source` parameter —
it implements `balance`, `has_autopay` and `tier_cap`, which is the whole protocol.

Reference data is deliberately absent. Tax profiles, commitment terms and catalog
rates keep coming off the database, because projecting forward does not change them.
The test for which side a datum falls on is one question: does my projection change it?
"""

import frappe

from central.billing.catalog.entitlements import cap_for, evaluate_tier, get_ladder
from central.billing.revenue import credits


class ProjectedWallet:
	"""One currency's balance, kept as the grants it came from rather than one number.

	The lots matter because promotional credit expires and purchased credit does not,
	so a wallet that is comfortably in the black today can be empty next month without
	anyone spending a penny. Draws take the soonest-expiring lot first — the same order
	the real ledger settles in, and the order that wastes the least of the customer's
	money.
	"""

	def __init__(self, lots=None):
		# [{"remaining": float, "expires_on": date|None}], soonest expiry first.
		self.lots = list(lots or [])

	@property
	def balance(self) -> float:
		return frappe.utils.flt(sum(lot["remaining"] for lot in self.lots), 2)

	def credit(self, amount, expires_on=None):
		self.lots.append({"remaining": frappe.utils.flt(amount), "expires_on": expires_on})
		self._sort()

	def draw(self, amount) -> float:
		"""Spend up to `amount`; returns what was actually available and taken."""
		wanted = frappe.utils.flt(amount)
		taken = 0.0
		for lot in self.lots:
			if wanted <= 0:
				break
			from_lot = min(lot["remaining"], wanted)
			lot["remaining"] -= from_lot
			wanted -= from_lot
			taken += from_lot
		self.lots = [lot for lot in self.lots if lot["remaining"] > 0]
		return frappe.utils.flt(taken, 2)

	def expire(self, on_date) -> float:
		"""Sweep grants whose date has passed; returns what was lost."""
		on_date = frappe.utils.getdate(on_date)
		lost = 0.0
		kept = []
		for lot in self.lots:
			if lot["expires_on"] and frappe.utils.getdate(lot["expires_on"]) <= on_date:
				lost += lot["remaining"]
			else:
				kept.append(lot)
		self.lots = kept
		return frappe.utils.flt(lost, 2)

	def _sort(self):
		import datetime

		self.lots.sort(
			key=lambda lot: frappe.utils.getdate(lot["expires_on"])
			if lot["expires_on"]
			else datetime.date.max
		)


class ProjectedState:
	"""Everything about a team that a projection changes as it rolls forward."""

	def __init__(
		self, team, currency, wallets, autopay, paid_count, paid_total, standing, base_cap=0.0
	):
		self.team = team
		self.currency = currency
		self.wallets = wallets
		self.autopay = autopay
		self.paid_count = paid_count
		self.paid_total = paid_total
		self.standing = standing
		# The floor the projected cap can never fall below: whichever is higher of the cap
		# the profile grants today (a manual override, a pinned level) and the cap the
		# team's history already earns. Computed once, at seed.
		#
		# This is load-bearing rather than defensive. Nothing guarantees the ladder's caps
		# rise with its rungs — a higher tier priced lower in one currency is a
		# configuration mistake, not an impossibility — and without a floor a projection
		# would then *shrink* a paying customer's ceiling as reward for paying. A
		# projection models promotion; it never demotes anyone.
		self.base_cap = max(frappe.utils.flt(base_cap), self._earned_cap())
		self.suspended_on = None
		self.events = []

	# ---- the source protocol the readers consult ---------------------------

	def balance(self, team, currency) -> float:
		return self.wallet(currency).balance

	def has_autopay(self, team) -> bool:
		return self.autopay

	def tier_cap(self, team) -> float:
		"""The cap the team's *projected* payment history earns it.

		Re-evaluated rather than remembered: settling invoices is how a team climbs the
		ladder, so a projection in which they pay every month must show the ceiling
		rising with them.

		It only ever rises. A projection models promotion, not demotion — and the team's
		live cap may come from a manual override or a level above what its history alone
		would score, neither of which paying more bills should take away.
		"""
		return max(self.base_cap, self._earned_cap())

	def _earned_cap(self) -> float:
		"""The cap this team's paid history scores on the live ladder."""
		levels = get_ladder()
		if not levels:
			return 0.0
		level = evaluate_tier(self.paid_count, self.paid_total, self.currency, levels)
		return frappe.utils.flt(cap_for(level, self.currency)) if level else 0.0

	# ---- evolution ---------------------------------------------------------

	def wallet(self, currency=None) -> ProjectedWallet:
		currency = currency or self.currency
		return self.wallets.setdefault(currency, ProjectedWallet())

	def settle(self, amount, currency=None) -> float:
		"""Draw what credits can cover; the rest is somebody else's problem."""
		return self.wallet(currency).draw(amount)

	def record_paid(self, amount):
		"""A settled invoice is what moves a team up the trust ladder."""
		self.paid_count += 1
		self.paid_total += frappe.utils.flt(amount)

	def expire_credits(self, on_date):
		lost = self.wallet().expire(on_date)
		if lost:
			self.events.append(
				{"date": str(on_date), "event": "Credits expired", "amount": lost}
			)
		return lost

	def suspend(self, on_date):
		"""Stop the clock. Accrual ends here — a stopped resource is not billed on."""
		if self.suspended_on:
			return
		self.suspended_on = frappe.utils.getdate(on_date)
		self.standing = "Suspended"
		self.events.append({"date": str(on_date), "event": "Suspended"})

	@property
	def suspended(self) -> bool:
		return self.suspended_on is not None


def seed(team: str, today=None) -> ProjectedState:
	"""Read the team once. Everything after this is arithmetic.

	Seeded from what is true now — including the paid history the trust ladder is
	scored on, so a projection starts the team exactly where the real ladder has them.
	"""
	today = frappe.utils.getdate(today or frappe.utils.nowdate())
	profile = frappe.db.get_value(
		"Billing Profile", team, ["currency", "collection_mode"], as_dict=True
	) or frappe._dict()
	currency = profile.currency or "INR"

	wallets = {}
	for row in credits.get_balances(team):
		lots = [
			{"remaining": lot.remaining, "expires_on": lot.expires_on}
			for lot in credits.credit_lots(team, row.currency)
			if lot.remaining > 0
		]
		wallets[row.currency] = ProjectedWallet(lots)
	wallets.setdefault(currency, ProjectedWallet())

	autopay = bool(
		frappe.get_all(
			"Payment Method",
			filters={
				"team": team,
				"method_type": ["in", ("Card", "UPI Autopay")],
				"status": "Active",
			},
			limit=1,
		)
	)

	paid = frappe.get_all(
		"Invoice",
		filters={"team": team, "status": "Paid", "invoice_type": "Billable"},
		fields=["total"],
	)
	standings = frappe.get_all("Subscription", filters={"team": team}, pluck="account_standing")

	from central.billing.catalog.entitlements import get_team_caps

	return ProjectedState(
		team=team,
		currency=currency,
		base_cap=frappe.utils.flt(get_team_caps(team).max_spend),
		wallets=wallets,
		autopay=autopay,
		paid_count=len(paid),
		paid_total=frappe.utils.flt(sum(frappe.utils.flt(p.total) for p in paid)),
		# The worst standing across the team's subscriptions is the one that decides
		# what happens next; a team is not "current" because one server still is.
		standing=_worst(standings),
	)


_STANDING_ORDER = ("Current", "Past Due", "Suspended", "Terminated")


def _worst(standings) -> str:
	present = [s for s in standings if s in _STANDING_ORDER]
	if not present:
		return "Current"
	return max(present, key=_STANDING_ORDER.index)
