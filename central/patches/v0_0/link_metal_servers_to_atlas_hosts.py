import frappe

from central.errors import AtlasConnectionError
from central.integrations.atlas import AtlasClient


def execute():
	"""Record the Atlas host of each active Metal Server that has none, so its servers and margin reach it."""
	for region in frappe.get_all("Region", pluck="name"):
		machines = frappe.get_all(
			"Metal Server",
			filters={"region": region, "status": "Active", "atlas_host_id": ["is", "not set"]},
			pluck="name",
		)
		if machines:
			link_region(region, machines)


def link_region(region: str, machines: list[str]) -> None:
	try:
		hosts = AtlasClient.for_operator(frappe.get_doc("Region", region)).list_hosts()
	except AtlasConnectionError:
		# A site that cannot reach this Atlas keeps the gap; readiness check R2 names it and Link Atlas Host fills it.
		frappe.log_error(
			title=f"Metal Server host link skipped region {region}", message=frappe.get_traceback()
		)
		return

	for name in machines:
		machine = frappe.get_doc("Metal Server", name)
		host_id = machine.find_atlas_host(hosts)
		if host_id:
			machine.db_set("atlas_host_id", host_id)
		else:
			frappe.log_error(
				title=f"Metal Server {name} has no Atlas host",
				message=f"No host in Atlas region {region} carries the name {name}.",
				reference_doctype="Metal Server",
				reference_name=name,
			)
