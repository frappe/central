import frappe

from central.billing.catalog.plan_setup import IP_RESOURCE_TYPE
from central.billing.catalog.subscriptions import cancel_subscription, latest_segment_by_subscription
from central.billing.catalog.taxonomy_setup import ensure_catalog_masters
from central.billing.revenue.public_ipv4_usage import held_addresses, write_ipv4_days
from central.billing.revenue.usage_ledger import utc_day_start, utc_today
from central.services.doctype.service.service import NETWORK_SERVICE, ensure_services


def execute():
	"""Bill public IPv4 per UTC day from today, and end each per-address subscription where today starts."""
	ensure_catalog_masters()
	ensure_services()
	today = utc_today()
	frappe.db.set_value("Service", NETWORK_SERVICE, "bill_from", today)
	close_address_subscriptions(utc_day_start(today))
	# The IP plan holds the price now; a second copy on the rate card would drift from it.
	frappe.db.delete("Catalog Rate", {"priced_doctype": "Resource Type", "priced_for": IP_RESOURCE_TYPE})
	write_ipv4_days(today, held_addresses())


def close_address_subscriptions(cutover) -> None:
	"""Cancel and disable every per-address subscription at `cutover`, so its segment ends as the days begin."""
	names = frappe.get_all(
		"Subscription", filters={"public_ip_server": ["is", "set"], "enabled": 1}, pluck="name"
	)
	latest = latest_segment_by_subscription(names)
	for name in names:
		last = latest.get(name)
		if not (last and last.change_type == "Cancelled"):
			# One opened or paused after the cutover closes there; that day bills as a Usage Day.
			effective_at = max(cutover, last.effective_at) if last else cutover
			cancel_subscription(name, effective_at=effective_at)
		frappe.get_doc("Subscription", name).disable()
