# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

STORAGE_SERVICE = "storage"
AI_SERVICE = "ai"
STORAGE_METER = "bytes_stored"
BYTES_PER_GB = 1_000_000_000

# Seeded disabled: an operator turns a service on once it holds the secret it signs with.
SERVICES = (
	{
		"service_name": STORAGE_SERVICE,
		"title": "Object Storage",
		"plan_category": "Remote Storage",
		"central_reads": 1,
		"meters": [
			{
				"meter_key": STORAGE_METER,
				"aggregation": "Level",
				"resource_type": "Storage",
				"unit": "GB",
				"unit_divisor": BYTES_PER_GB,
				"label": "Storage",
			},
		],
	},
)


class Service(Document):
	def validate(self) -> None:
		seen = set()
		for meter in self.meters:
			if meter.meter_key in seen:
				frappe.throw(_("Meter {0} is listed twice.").format(meter.meter_key))
			if frappe.utils.flt(meter.unit_divisor) <= 0:
				frappe.throw(_("Meter {0} needs a unit divisor above zero.").format(meter.meter_key))
			seen.add(meter.meter_key)

	def get_meter(self, meter_key: str):
		"""The meter row named `meter_key`, or None."""
		return next((meter for meter in self.meters if meter.meter_key == meter_key), None)


def ensure_services() -> None:
	"""Seed the services Central already talks to. An existing record is left as an operator set it."""
	for spec in SERVICES:
		if frappe.db.exists("Service", spec["service_name"]):
			continue
		# Reference data seeded at install and migrate, before any user exists.
		frappe.get_doc({"doctype": "Service", "enabled": 0, **spec}).insert(ignore_permissions=True)
