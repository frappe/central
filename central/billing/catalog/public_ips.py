from __future__ import annotations

from typing import TYPE_CHECKING

import frappe
from frappe import _

from central.billing.catalog.pricing import resolve_component_rate
from central.billing.catalog.subscriptions import cancel_subscription
from central.billing.doctype.billing_profile.billing_profile import get_team_currency

if TYPE_CHECKING:
	from central.infrastructure.doctype.virtual_machine.virtual_machine import VirtualMachine

IP_RESOURCE = "IP"


def get_public_ipv4_rate(team: str, region: str) -> tuple[float | None, str]:
	"""The team's monthly price for one public IPv4 in `region`, and its currency. The rate is
	the `IP` Resource Type's Catalog Rate, so an operator changes it there. IPv6 is free."""
	currency = get_team_currency(team)
	return resolve_component_rate(IP_RESOURCE, currency, region), currency


def require_public_ipv4_rate(team: str, region: str) -> None:
	"""Refuse a public IPv4 in a region with no price, so no address is ever free by accident."""
	rate, currency = get_public_ipv4_rate(team, region)
	if rate is None:
		frappe.throw(_("A public IPv4 address has no price in {0} for this region yet.").format(currency))


def open_public_ipv4_subscription(server: VirtualMachine) -> None:
	"""Start billing the server's public IPv4, from now until Atlas no longer reports it.

	Atlas has already attached the address, so a missing price is logged for an operator
	instead of failing the state report."""
	rate, currency = get_public_ipv4_rate(server.team, server.region)
	if rate is None:
		frappe.log_error(
			title=f"No public IPv4 price for {server.name}",
			message=f"Region {server.region} has no IP Catalog Rate in {currency}.",
		)
		return

	subscription = frappe.get_doc(
		{
			"doctype": "Subscription",
			"team": server.team,
			"public_ip_server": server.name,
			"pricing_mode": "Composed",
			"includes": [{"resource_type": IP_RESOURCE, "quantity": 1, "unit": "Nos"}],
			"billing_cycle": "Monthly",
			"account_standing": "Current",
			"enabled": 1,
		}
	)
	subscription.flags.opening_quote = (rate, currency)
	# A system step of the server lifecycle; customers never write billing records.
	subscription.insert(ignore_permissions=True)


def close_public_ipv4_subscription(subscription: str) -> None:
	"""Stop billing a detached or released address. Its closed segments stay on the invoice."""
	cancel_subscription(subscription)
	frappe.get_doc("Subscription", subscription).disable()
