import frappe

from central.billing.catalog.taxonomy_setup import ensure_catalog_masters
from central.services.doctype.service.service import AI_SERVICE, ensure_services

# The key before a day could be split by model. It would refuse a second model on the same day.
OLD_UNIQUE = "unique_usage_day"


def execute():
	"""Start billing AI from today: register it, keep the one-row-per-model key, subscribe its teams."""
	# Imported here, so the patch still loads when the billing modules it uses change.
	from central.billing.revenue.grove_bridge import subscribe_ai_teams
	from central.billing.revenue.usage_ledger import utc_today

	ensure_catalog_masters()
	ensure_services()
	if frappe.db.table_exists("Usage Day") and frappe.db.has_index("tabUsage Day", OLD_UNIQUE):
		frappe.db.sql_ddl("alter table `tabUsage Day` drop index `unique_usage_day`")
	# Usage before today was never billed and is not billed now; a backfill keeps it written off.
	if not frappe.db.get_value("Service", AI_SERVICE, "bill_from"):
		frappe.db.set_value("Service", AI_SERVICE, "bill_from", utc_today())
	subscribe_ai_teams()
