# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ServiceMeter(Document):
	def get_day_row(self, team_service, day, value: float, **values) -> dict:
		"""A day line for one subject's raw value of this meter on a UTC day."""
		return {
			"service": self.parent,
			"meter": self.meter_key,
			"subject": team_service.external_id,
			"day": day,
			"aggregation": self.aggregation,
			"team": team_service.team,
			"subscription": team_service.subscription,
			"resource_type": self.resource_type,
			"quantity": value / frappe.utils.flt(self.unit_divisor),
			"unit": self.unit,
			**values,
		}
