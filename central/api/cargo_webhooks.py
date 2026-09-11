## This file will now only accept webhooks from Cargo, and will make appropriate calls based on that.
import typing

import frappe

from central.integrations.cargo_webhook import verify_cargo_webhook

if typing.TYPE_CHECKING:
	from central.central.doctype.cargo_instance.cargo_instance import CargoInstance
	from central.services.doctype.service_backend.service_backend import ServiceBackend


# nosemgrep: guest-whitelisted-method -- verify_cargo_webhook authenticates the caller below.
@frappe.whitelist(allow_guest=True, methods=["POST"])
@verify_cargo_webhook
def object_storage_cluster_webhook(region: str, status: str, service_endpoint: str) -> None:
	"""A once cargo's object storage cluster is up we need to inform central.
	The following function will be called via webhook and perform the following functions
	 - Create service backend if not present for the storage.regions
	 - Update the service backend with the new information provided by cargo
	"""

	# Check if the service backend exists for the given storage:region
	backend = frappe.db.get_value("Service Backend", {"service": "storage", "region": region}, "name")
	service_backend: ServiceBackend = (
		frappe.get_doc("Service Backend", backend) if backend else frappe.new_doc("Service Backend")
	)

	# Update the service backend with the new information provided by cargo
	service_backend.service = "storage"
	service_backend.region = region
	service_backend.is_active = status == "Active"
	service_backend.service_endpoint = service_endpoint

	# We are sure this came from cargo since we verified therefore ignore permissions
	service_backend.save(ignore_permissions=True)

	# Register/Active the CargoInstance in case it wasn't registered yet.
	# Not sure wtf this is doing but keeping it for now since it was in the original code.
	cargo_instance: CargoInstance = frappe.get_doc("Cargo Instance", {"region": region})

	if not cargo_instance.registered_at:
		cargo_instance.registered_at = frappe.utils.now()

	cargo_instance.status = "Registered"
	cargo_instance.save(ignore_permissions=True)
