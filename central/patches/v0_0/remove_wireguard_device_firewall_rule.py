import frappe


def execute():
	"""Remove the rule that let every WireGuard VPN device pass the firewall, from every live
	server at Atlas. The job reads each server first, so its stored rules are current."""
	frappe.enqueue(
		"central.integrations.servers.remove_legacy_device_rules", queue="long", enqueue_after_commit=True
	)
