import frappe

from central.services.doctype.service.service import (
	AI_EVIDENCE_KEYS,
	AI_METER,
	AI_SERVICE,
	STORAGE_EVIDENCE_KEYS,
	STORAGE_METER,
	STORAGE_SERVICE,
	ensure_services,
)

KEYS = {
	(STORAGE_SERVICE, STORAGE_METER): STORAGE_EVIDENCE_KEYS,
	(AI_SERVICE, AI_METER): AI_EVIDENCE_KEYS,
}


def execute():
	"""Name the evidence keys of the storage and AI meters. A key list an operator set is kept."""
	ensure_services()
	for (service, meter), keys in KEYS.items():
		frappe.db.set_value(
			"Service Meter",
			{
				"parent": service,
				"parenttype": "Service",
				"meter_key": meter,
				"evidence_keys": ["is", "not set"],
			},
			"evidence_keys",
			keys,
			update_modified=False,
		)
