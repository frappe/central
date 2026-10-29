import frappe
from frappe import _

from central.billing import settings
from central.billing.payments.provisioning import grant_welcome_credits, has_owner_received_welcome_credits
from central.billing.revenue.credits import get_balance, grant_promotional_credits
from central.signups.eligibility import get_team_open_trial, has_active_payment_method
from central.signups.trial import convert_team


def on_payment_method_update(doc, method: str | None = None) -> None:
	"""Grant the welcome credit and convert the team's trials when its payment method becomes active. A gateway
	creates every method as Pending Validation, so activation is always a status change."""
	before = doc.get_doc_before_save()
	if doc.status != "Active" or not before or before.status == "Active":
		return

	# Checked before the conversion, which closes the team's open trials.
	if is_welcome_credit_due(doc.team):
		grant_welcome_credits(doc.team)
	convert_team(doc.team)


def is_welcome_credit_due(team: str) -> bool:
	"""A team earns the welcome credit with its first payment method, unless it had a free trial:
	the trial site is that team's free start."""
	return not frappe.db.exists("Site", {"team": team, "trial_state": ["is", "set"]})


@frappe.whitelist(methods=["POST"])
def grant_credit(team: str, amount: float, validity_days: int, note: str) -> dict:
	"""Operator action: grant promotional credit, such as a beta credit, to `team` now.

	It counts as the owner's welcome credit, so the team gets no welcome credit later."""
	frappe.only_for("System Manager")
	if amount <= 0 or validity_days <= 0:
		frappe.throw(_("Enter a positive amount and a positive validity."))

	currency = frappe.db.get_value("Billing Profile", team, "currency")
	if not currency:
		frappe.throw(_("Team {0} has no billing currency yet.").format(team))

	expires_on = frappe.utils.add_days(frappe.utils.nowdate(), validity_days)
	return grant_promotional_credits(team, amount, currency, note=note, expires_on=expires_on)


def get_purchase_state(team: str) -> dict:
	"""What the console shows before a server is bought: whether a payment method is needed,
	the welcome credit the first one adds, and the open trial it converts. The server checks
	again on create."""
	collection_mode = frappe.db.get_value("Billing Profile", team, "collection_mode")
	is_required = bool(
		frappe.get_cached_value("Central Settings", "Central Settings", "require_payment_method")
		and collection_mode != "Manual Checkout"
		and not has_active_payment_method(team)
		and get_balance(team)["balance"] <= 0
	)
	return {
		"payment_method_required": is_required,
		"welcome_credit": get_welcome_credit_offer(team),
		"open_trial": get_team_open_trial(team),
	}


def get_welcome_credit_offer(team: str) -> dict | None:
	"""The welcome credit the team's first active payment method adds, or None."""
	currency = frappe.db.get_value("Billing Profile", team, "currency")
	amount = settings.welcome_credit_amount(currency) if currency else 0
	if not amount or has_owner_received_welcome_credits(team, lock=False) or not is_welcome_credit_due(team):
		return None

	return {
		"amount": amount,
		"currency": currency,
		"validity_days": settings.promotional_credit_validity_days(),
	}
