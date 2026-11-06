import frappe

from central.billing import settings
from central.billing.india_gst import INDIA


def execute() -> None:
	"""GST is mandatory in India. Set it on an Indian team's Tax Profile that is not zero-rated."""
	for team in untaxed_indian_teams():
		frappe.db.set_value(
			"Tax Profile", team, {"output_tax_type": "GST", "output_tax_rate": settings.default_gst_rate()}
		)


def untaxed_indian_teams() -> list[str]:
	tax = frappe.qb.DocType("Tax Profile")
	profile = frappe.qb.DocType("Billing Profile")
	return (
		frappe.qb.from_(tax)
		.join(profile)
		.on(profile.name == tax.team)
		.select(tax.team)
		.where((tax.output_tax_type != "GST") | tax.output_tax_type.isnull())
		.where(tax.zero_rated == 0)
		.where((profile.country == INDIA) | (profile.currency == "INR"))
		.run(pluck=True)
	)
