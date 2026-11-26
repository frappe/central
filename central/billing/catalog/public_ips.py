import frappe
from frappe import _

from central.billing.catalog.plan_setup import IP_RESOURCE_TYPE
from central.billing.catalog.pricing import get_catalog_rates, resolve_rate
from central.billing.doctype.billing_profile.billing_profile import get_team_currency


def get_public_ipv4_rate(team: str, region: str) -> tuple[float | None, str]:
	"""The team's monthly price for one public IPv4 in `region`, and its currency. IPv6 is free."""
	currency = get_team_currency(team)
	return resolve_rate(get_public_ipv4_rates(), currency, region), currency


def get_public_ipv4_rates() -> list:
	"""The Catalog Rates of the metered plan that bills public IPv4 addresses, empty while there is none."""
	from central.billing.revenue.metering import metered_plan_for

	# The invoice reads this plan's rate too, so the console, the guards and the bill show one price.
	plan = metered_plan_for(IP_RESOURCE_TYPE)
	return get_catalog_rates("Plan", plan.name) if plan else []


def require_public_ipv4_rate(team: str, region: str) -> None:
	"""Refuse a public IPv4 in a region with no price, so no address is ever free by accident."""
	rate, currency = get_public_ipv4_rate(team, region)
	if rate is None:
		frappe.throw(_("A public IPv4 address has no price in {0} for this region yet.").format(currency))
