import frappe
from frappe import _
from frappe.model.naming import getseries
from frappe.query_builder.functions import Max

TENANT_ID_SERIES = "TENANT-ID"
MAXIMUM_TENANT_ID = 0xFFFFFFFF


def allocate_tenant_id() -> int:
	"""Allocate under the Framework series lock, in the Team's transaction."""
	tenant_id = int(getseries(TENANT_ID_SERIES, 10))
	validate_tenant_id(tenant_id)
	return tenant_id


def validate_tenant_id(tenant_id: int | None) -> None:
	if type(tenant_id) is not int or not 1 <= tenant_id <= MAXIMUM_TENANT_ID:
		frappe.throw(_("The tenant ID must be a whole number from 1 to 4294967295."))


def prepare_tenant_id_series() -> None:
	"""Preserve the allocation counter and any imported tenant IDs during schema setup."""
	team = frappe.qb.DocType("Team")
	maximum = frappe.qb.from_(team).select(Max(team.tenant_id)).run()[0][0] or 0
	current = int(getseries(TENANT_ID_SERIES, 10))
	if maximum > current:
		series = frappe.qb.DocType("Series")
		frappe.qb.update(series).set(series.current, maximum).where(series.name == TENANT_ID_SERIES).run()
