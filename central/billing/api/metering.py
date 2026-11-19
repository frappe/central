# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe

from central.billing.revenue import service_reports

SERVICE_HEADER = "X-Central-Service"
SIGNATURE_HEADER = "X-Central-Signature"


# nosemgrep: guest-whitelisted-method -- accept_report checks the service's signature before it reads the body.
@frappe.whitelist(allow_guest=True, methods=["POST"])
def report() -> dict:
	"""Take one signed usage report from a service."""
	return service_reports.accept_report(
		service_name=frappe.get_request_header(SERVICE_HEADER),
		signature=frappe.get_request_header(SIGNATURE_HEADER),
		raw_body=frappe.request.get_data(),
	)
