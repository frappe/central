import frappe

from central.infrastructure.doctype.vm_snapshot.vm_snapshot import apply_free_allowance


def execute():
	"""Stop the free snapshot allowance and open billing for each snapshot that was free."""
	frappe.db.set_single_value("Billing Settings", "free_snapshots_per_server", 0)

	servers = frappe.get_all(
		"VM Snapshot", filters={"status": "Available", "is_free": 1}, pluck="server", distinct=True
	)
	for server in servers:
		apply_free_allowance(server)
