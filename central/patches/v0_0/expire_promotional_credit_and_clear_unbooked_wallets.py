import frappe
from frappe.utils import add_days, flt, getdate

from central.billing import settings
from central.billing.revenue import credits

DRIFT_TOLERANCE = 0.001


def execute() -> None:
	set_expiry_on_promotional_credit()
	clear_balances_with_no_ledger_entry()


def set_expiry_on_promotional_credit() -> None:
	"""Every promotional credit expires its validity period after the day it was granted."""
	days = settings.promotional_credit_validity_days()
	for entry in frappe.get_all(
		"Credit Ledger Entry",
		filters={
			"entry_type": "Credit",
			"reference_type": "Promotion",
			"paid_in": 0,
			"expires_on": ["is", "not set"],
		},
		fields=["name", "creation"],
	):
		expires_on = add_days(getdate(entry.creation), days)
		frappe.db.set_value(
			"Credit Ledger Entry", entry.name, "expires_on", expires_on, update_modified=False
		)


def clear_balances_with_no_ledger_entry() -> None:
	"""The ledger holds the truth: a wallet above its ledger drops to what the ledger proves."""
	for wallet in frappe.get_all("Credit Wallet", fields=["name", "team", "currency", "balance"]):
		proven = credits.ledger_balance(wallet.team, wallet.currency)
		if flt(wallet.balance) - proven > DRIFT_TOLERANCE:
			frappe.db.set_value("Credit Wallet", wallet.name, "balance", proven, update_modified=False)
