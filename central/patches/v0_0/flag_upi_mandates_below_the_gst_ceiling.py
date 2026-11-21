import frappe

from central.billing.payments import mandates
from central.billing.platform.jobs import each_isolated


def execute() -> None:
	"""Flag each active UPI mandate registered below the cap with GST, and ask its team once to re-authorise it."""
	teams = frappe.get_all(
		"Payment Method",
		filters={"method_type": mandates.MANDATE_METHOD, "status": "Active"},
		pluck="team",
		distinct=True,
	)
	each_isolated(
		"Flag UPI mandates below the GST ceiling", "Team", teams, mandates.reconcile_mandates_to_cap
	)
