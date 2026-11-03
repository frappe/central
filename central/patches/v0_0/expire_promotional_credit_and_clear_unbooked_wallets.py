import frappe
from frappe.utils import add_days, flt, getdate

from central.billing import settings
from central.billing.revenue import credits

DRIFT_TOLERANCE = 0.001


def execute() -> None:
	set_expiry_on_promotional_credit()
	book_missing_wallet_credit()


def set_expiry_on_promotional_credit() -> None:
	"""Every promotional credit expires its validity period after the day it was granted."""
	days = settings.promotional_credit_validity_days()
	for entry in credits.promotional_credit_without_expiry():
		expires_on = add_days(getdate(entry.creation), days)
		frappe.db.set_value(
			"Credit Ledger Entry", entry.name, "expires_on", expires_on, update_modified=False
		)


def book_missing_wallet_credit() -> None:
	"""A wallet above its ledger holds credit that the ledger never booked. Book that credit, so that
	the ledger proves the balance. A wallet below its ledger stays as it is, for an operator."""
	for wallet in frappe.get_all("Credit Wallet", pluck="name"):
		_book_missing_credit(wallet)


def _book_missing_credit(wallet_name: str) -> None:
	wallet = frappe.db.get_value(
		"Credit Wallet",
		wallet_name,
		["name", "team", "currency", "balance", "last_entry", "creation"],
		as_dict=True,
		for_update=True,
	)
	precision = frappe.get_precision("Credit Ledger Entry", "amount") or 2
	missing = flt(flt(wallet.balance) - credits.ledger_balance(wallet.team, wallet.currency), precision)
	if missing <= DRIFT_TOLERANCE:
		return

	entry = _repair_entry(wallet, missing)
	# The entry is inserted without hooks, so the migration enqueues no settlement job.
	entry.db_insert()
	if not wallet.last_entry:
		frappe.db.set_value("Credit Wallet", wallet.name, "last_entry", entry.name, update_modified=False)


def _repair_entry(wallet, amount: float):
	return frappe.get_doc(
		{
			"doctype": "Credit Ledger Entry",
			"team": wallet.team,
			"currency": wallet.currency,
			"entry_type": "Credit",
			"amount": amount,
			"paid_in": 0,
			"running_balance": flt(wallet.balance),
			"reference_type": "Ledger Repair",
			"reference_name": wallet.name,
			"note": "The wallet held this credit with no ledger entry. This entry books it.",
			"created_at": wallet.creation,
			"expires_on": add_days(getdate(wallet.creation), settings.promotional_credit_validity_days()),
		}
	)
