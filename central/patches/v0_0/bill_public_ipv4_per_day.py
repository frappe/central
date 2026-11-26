import datetime

import frappe
from frappe import _

from central.billing.catalog.plan_setup import IP_RESOURCE_TYPE
from central.billing.catalog.pricing import get_catalog_rates, set_catalog_rate
from central.billing.catalog.subscriptions import cancel_subscription, latest_segment_by_subscription
from central.billing.catalog.taxonomy_setup import ensure_catalog_masters
from central.billing.revenue.metering import metered_plan_for
from central.billing.revenue.public_ipv4_usage import held_addresses, write_ipv4_days
from central.billing.revenue.usage_ledger import utc_day_start, utc_today
from central.services.doctype.service.service import NETWORK_SERVICE, ensure_services


def execute():
	"""Bill public IPv4 per UTC day from today, and end each per-address subscription where today starts."""
	ensure_catalog_masters()
	ensure_services()
	move_ip_rates_to_plan()
	today = utc_today()
	# A second run on a later day keeps the first cutover day.
	if not frappe.db.get_value("Service", NETWORK_SERVICE, "bill_from"):
		frappe.db.set_value("Service", NETWORK_SERVICE, "bill_from", today)
	close_address_subscriptions(utc_day_start(today))
	write_ipv4_days(today, held_addresses())


def move_ip_rates_to_plan() -> None:
	"""Copy each IP rate card price, regional ones too, onto the plan that bills public IPv4, then delete it."""
	plan = metered_plan_for(IP_RESOURCE_TYPE)
	if not plan:
		# The rate card is deleted below, so its prices must have somewhere to go first.
		frappe.throw(
			_(
				"No active metered plan bills public IPv4. Activate the public-ipv4 plan and run the patch again."
			)
		)
	for row in get_catalog_rates("Resource Type", IP_RESOURCE_TYPE):
		set_catalog_rate("Plan", plan.name, row.currency, row.rate, cluster=row.cluster)
	# The plan holds the price now; a second copy on the rate card would drift from it.
	frappe.db.delete("Catalog Rate", {"priced_doctype": "Resource Type", "priced_for": IP_RESOURCE_TYPE})


def close_address_subscriptions(cutover: datetime.datetime) -> None:
	"""Cancel and disable every per-address subscription at `cutover`, so its segment ends as the days begin."""
	names = frappe.get_all(
		"Subscription", filters={"public_ip_server": ["is", "set"], "enabled": 1}, pluck="name"
	)
	latest = latest_segment_by_subscription(names)
	for name in names:
		last = latest.get(name)
		if not (last and last.change_type == "Cancelled"):
			# The cancel never comes before the last change, so the ledger stays in time order.
			# One opened today then bills no hour, and its day bills as a Usage Day.
			# One paused or detached after 00:00 and then resumed or re-attached closes at the
			# resume, and its server gets no Usage Day today, so the hours after it go unbilled:
			# at most one address-day per such server, once, and never a double charge.
			effective_at = max(cutover, last.effective_at) if last else cutover
			cancel_subscription(name, effective_at=effective_at)
		frappe.get_doc("Subscription", name).disable()
