import frappe
from frappe import _

from central.billing.api.dashboard._shared import _team_currency
from central.billing.catalog.pricing import resolve_component_rate
from central.billing.catalog.subscriptions import cancel_subscription

SNAPSHOT_RESOURCE = "Snapshot"


def get_snapshot_rate(team: str, region: str) -> tuple[float | None, str]:
	"""The team's price per GB-month for snapshot storage in `region`, and its currency.
	The rate is the `Snapshot` Resource Type's Catalog Rate, so an operator changes it there."""
	currency = _team_currency(team)
	return resolve_component_rate(SNAPSHOT_RESOURCE, currency, region), currency


def open_snapshot_subscription(team: str, snapshot: str, region: str, size_gib: int) -> str:
	"""Start billing a snapshot by its size, from now until it is deleted. A region with no
	Snapshot rate is refused, so a snapshot is never kept for free by accident."""
	rate, currency = get_snapshot_rate(team, region)
	if rate is None:
		frappe.throw(_("Snapshot storage has no price in {0} for this region yet.").format(currency))

	subscription = frappe.get_doc(
		{
			"doctype": "Subscription",
			"team": team,
			"vm_snapshot": snapshot,
			"pricing_mode": "Composed",
			"includes": [{"resource_type": SNAPSHOT_RESOURCE, "quantity": size_gib, "unit": "GB"}],
			"billing_cycle": "Monthly",
			"account_standing": "Current",
			"enabled": 1,
		}
	)
	# Lock the price the console showed, so the bill and the quote cannot disagree.
	subscription.flags.opening_quote = (rate * size_gib, currency)
	# A system step of the snapshot lifecycle; customers never write billing records.
	subscription.insert(ignore_permissions=True)
	return subscription.name


def close_snapshot_subscription(subscription: str) -> None:
	"""Stop billing a deleted snapshot. Its closed segments stay on the invoice."""
	cancel_subscription(subscription)
	frappe.get_doc("Subscription", subscription).disable()


def snapshot_regions(snapshots: list[str]) -> dict[str, str]:
	"""Map each snapshot to its region in one query, for invoicing."""
	names = [name for name in set(snapshots) if name]
	if not names:
		return {}

	rows = frappe.get_all("VM Snapshot", filters={"name": ["in", names]}, fields=["name", "region"])
	return {row.name: row.region for row in rows}
