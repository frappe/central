import frappe

SERVER_LIMITS = {
	"disk_iops": 3000,
	"disk_throughput_mibps": 125,
	"private_network_throughput_mibps": 500,
	"public_network_throughput_mibps": 500,
}


def execute():
	"""Give an existing site the server limits its new fields default to.

	A field default applies only when the Single document is first created, so a site that
	already had Central Settings reads these fields as zero, and Atlas would get no limit."""
	for fieldname, value in SERVER_LIMITS.items():
		if not frappe.db.get_single_value("Central Settings", fieldname):
			frappe.db.set_single_value("Central Settings", fieldname, value)
