import re

import frappe

from central.errors import AtlasConnectionError
from central.integrations.atlas import AtlasClient


def execute():
	"""Name each active Metal Server as its Atlas host is titled, and record the host's ID.

	Central named the machines with the city (metal-mumbai-1) and Atlas titles the
	hosts with the region code (metal-bom-1). With one name in both, Link Atlas Host
	finds the host, and servers and margins reach their machine.
	"""
	for region in frappe.get_all("Region", pluck="name"):
		machines = frappe.get_all(
			"Metal Server", filters={"region": region, "status": "Active"}, fields=["name", "atlas_host_id"]
		)
		if machines:
			link_region(region, machines)


def link_region(region: str, machines: list[dict]) -> None:
	try:
		hosts = AtlasClient.for_operator(frappe.get_doc("Region", region)).list_hosts()
	except AtlasConnectionError:
		# A site that cannot reach this Atlas keeps the old names; readiness check R2 names the gap.
		frappe.log_error(title=f"Metal Server rename skipped region {region}", message=frappe.get_traceback())
		return

	for machine in machines:
		host = find_host(machine, region, hosts)
		if host:
			link_machine(machine, host)
		else:
			log_unmatched(machine.name, f"No host in Atlas region {region} matches {machine.name}.")


def find_host(machine: dict, region: str, hosts: list[dict]) -> dict | None:
	"""The host with the machine's recorded ID, else the host titled with its name or region-code name."""
	if machine.atlas_host_id:
		return next((host for host in hosts if host["id"] == machine.atlas_host_id), None)
	titles = {machine.name, re.sub(r"^metal-[^-]+-", f"metal-{region}-", machine.name)}
	return next((host for host in hosts if host.get("title") in titles), None)


def link_machine(machine: dict, host: dict) -> None:
	name = machine.name
	title = host.get("title")
	if title and title != name:
		if frappe.db.exists("Metal Server", title):
			log_unmatched(name, f"Metal Server {title} already exists, so {name} keeps its name and no host.")
			return
		name = frappe.rename_doc(
			"Metal Server", name, title, force=True, rebuild_search=False, show_alert=False
		)
	if not machine.atlas_host_id:
		frappe.db.set_value("Metal Server", name, "atlas_host_id", host["id"])


def log_unmatched(name: str, message: str) -> None:
	frappe.log_error(
		title=f"Metal Server {name} not renamed to its Atlas host",
		message=message,
		reference_doctype="Metal Server",
		reference_name=name,
	)
