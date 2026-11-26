# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils.password import get_decrypted_password

STORAGE_SERVICE = "storage"
AI_SERVICE = "ai"
STORAGE_METER = "bytes_stored"
AI_METER = "cost"
NETWORK_SERVICE = "network"
PUBLIC_IPV4_METER = "public_ipv4"
BYTES_PER_GB = 1_000_000_000
# Grove keeps cost to nine decimal places of a dollar.
NANO_PER_UNIT = 1_000_000_000

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
	{
		"service_name": AI_SERVICE,
		"title": "AI",
		"plan_category": "AI Tokens",
		"central_reads": 1,
		"meters": [
			{
				"meter_key": AI_METER,
				"aggregation": "Sum",
				"resource_type": "AI Usage",
				"unit": "USD",
				"unit_divisor": NANO_PER_UNIT,
				"cost_currency": "USD",
				"allow_negative": 1,
				"label": "AI",
			},
		],
	},
	{
		# Central counts the public IPv4 addresses each server holds; no other service reports them.
		"service_name": NETWORK_SERVICE,
		"title": "Network",
		"plan_category": "Live Metered Resources",
		"central_reads": 1,
		"meters": [
			{
				"meter_key": PUBLIC_IPV4_METER,
				"aggregation": "Level",
				"resource_type": "IP",
				"unit": "Nos",
				"unit_divisor": 1,
				"label": "Public IPv4",
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
		# Frappe masks a stored password before `on_update`, so only a newly typed one is unmasked here.
		self.flags.has_new_report_secret = bool(self.report_secret) and not self.is_dummy_password(
			self.report_secret
		)
		if self.flags.has_new_report_secret:
			self.start_secret_delivery()
		else:
			self.keep_secret_delivery()

	def start_secret_delivery(self) -> None:
		"""Give each host of the new secret a Pending row, under a new run."""
		from central.integrations.report_secret import delivery_targets

		self.secret_run = frappe.generate_hash(length=12)
		self.set(
			"secret_deliveries",
			[
				{"host": host, "region": region, "status": "Pending", "run": self.secret_run}
				for host, region in delivery_targets(self.name)
			],
		)
		self.secret_delivery_status = get_secret_delivery_status(
			[row.status for row in self.secret_deliveries]
		)

	def keep_secret_delivery(self) -> None:
		"""Keep the delivery rows as the jobs wrote them."""
		# Only the jobs write these rows. A form opened before a job ended must not save its old copy.
		before = self.get_doc_before_save()
		if not before:
			return
		self.set("secret_deliveries", [row.as_dict() for row in before.secret_deliveries])
		self.secret_delivery_status = before.secret_delivery_status
		self.secret_run = before.secret_run

	def on_update(self) -> None:
		if self.flags.has_new_report_secret:
			from central.integrations.report_secret import send_report_secret

			send_report_secret(self.name)

	def get_meter(self, meter_key: str):
		"""The meter row named `meter_key`, or None."""
		return next((meter for meter in self.meters if meter.meter_key == meter_key), None)


def get_secret_delivery_status(statuses: list[str]) -> str:
	"""The Service's summary of its delivery rows."""
	for status in ("Failed", "Pending"):
		if status in statuses:
			return status
	return "Delivered" if statuses else ""


def is_read_by_central(service: str) -> bool:
	"""Central still reads the service's usage itself, rather than taking its reports."""
	return bool(frappe.db.get_value("Service", service, "central_reads"))


def is_read_by_central_locked(service: str) -> bool:
	"""Whether Central reads the service itself, read under the Service row lock."""
	# Pushed reports and Central's own page jobs both decide under this lock and keep it until they
	# commit, so a day is written by only one of them whichever way the switch is flipped.
	return bool(frappe.db.get_value("Service", service, "central_reads", for_update=True))


def get_report_secret(service: str) -> str | None:
	"""The secret `service` signs its reports with, or None while it has none."""
	return get_decrypted_password("Service", service, "report_secret", raise_exception=False) or None


def ensure_services() -> None:
	"""Seed the services Central already talks to. An existing record is left as an operator set it."""
	for spec in SERVICES:
		if frappe.db.exists("Service", spec["service_name"]):
			continue
		# Reference data seeded at install and migrate, before any user exists.
		frappe.get_doc({"doctype": "Service", "enabled": 0, **spec}).insert(ignore_permissions=True)


def on_doctype_update():
	frappe.db.add_index("Service", ["secret_delivery_status"])
