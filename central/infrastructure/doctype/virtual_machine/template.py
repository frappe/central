from __future__ import annotations

from typing import Literal

import frappe
from frappe import _
from frappe.utils import now_datetime

from central.infrastructure.doctype.region.region import Region
from central.sso import verify_template_ready_token

Phase = Literal["booking", "server", "app", "ready", "failed"]

REGION_FIELDS = ["display_name", "country_code", "latitude", "longitude"]


def record_ready(token: str) -> None:
	"""Mark the server of a template creation ready. A repeated report changes nothing."""
	action = verify_template_ready_token(token)
	server = frappe.db.get_value("Resource Action", {"name": action, "action": "create"}, "server")
	# The server reports before Central has its record only when the region is slow to answer,
	# so the server sends again.
	if not server:
		frappe.throw(_("This server is not recorded yet."), frappe.DoesNotExistError)

	machine = frappe.get_doc("Virtual Machine", server, for_update=True)
	if machine.app_ready_at:
		return

	machine.db_set("app_ready_at", now_datetime())
	machine.publish_state_change()


def route_chosen_name(server: str) -> None:
	"""Route the name a template server was created with, once it has an address. It runs on
	every report and queues the route once."""
	action = _get_creation(server)
	if not action or not action.subdomain:
		return
	if not frappe.db.get_value("Virtual Machine", server, "ipv6_address"):
		return
	if frappe.db.exists("Site Domain", get_chosen_domain(action)):
		return

	frappe.enqueue(
		"central.infrastructure.doctype.virtual_machine.template.insert_route",
		queue="short",
		job_id=f"template-route:{server}",
		deduplicate=True,
		enqueue_after_commit=True,
		server=server,
	)


def insert_route(server: str) -> None:
	"""Insert the Site Domain for the chosen name. A job keeps a refused name from stopping the
	server's report."""
	action = _get_creation(server)
	domain = get_chosen_domain(action)
	if frappe.db.exists("Site Domain", domain):
		return

	route = frappe.get_doc(
		{
			"doctype": "Site Domain",
			"domain": domain,
			"team": action.team,
			"server": server,
			"region": action.region,
		}
	)
	# The system routes the name the customer chose at creation; no user acts here.
	route.insert(ignore_permissions=True)


def get_journey(action_name: str) -> dict:
	"""Where a template server is on its way to its first answer, in the shape the setup journey
	reads."""
	action = frappe.get_doc("Resource Action", action_name)
	action.check_permission("read")

	domain = get_chosen_domain(action) if action.subdomain else None
	region = frappe.get_cached_value("Region", action.region, REGION_FIELDS, as_dict=True)

	return {
		"phase": get_phase(action, domain),
		"subdomain": action.subdomain,
		"domain": domain.removeprefix(f"{action.subdomain}.") if domain else None,
		"url": f"https://{domain}" if domain else None,
		"server": action.server,
		"region": {
			"title": region.display_name,
			"country_code": region.country_code,
			"latitude": region.latitude,
			"longitude": region.longitude,
		},
		"started_at": action.creation,
		"eta_seconds": None,
		"reference": action.name,
	}


def get_phase(action, domain: str | None) -> Phase:
	"""Ready needs the application's own report, and the chosen name routed when there is one."""
	machine = (
		frappe.db.get_value("Virtual Machine", action.server, ["status", "app_ready_at"], as_dict=True)
		if action.server
		else None
	) or frappe._dict()

	if action.status in ("Failed", "Timed Out") or machine.status == "Failed":
		return "failed"
	if machine.app_ready_at and (
		not domain or frappe.db.get_value("Site Domain", domain, "status") == "Active"
	):
		return "ready"
	if machine.status == "Running":
		return "app"
	if action.status in ("Queued", "Dispatching"):
		return "booking"
	return "server"


def get_chosen_domain(action) -> str:
	return f"{action.subdomain}.{Region.get_zone(action.region)}"


def _get_creation(server: str):
	return frappe.db.get_value(
		"Resource Action",
		{"server": server, "action": "create", "resource_type": "Server"},
		["subdomain", "team", "region"],
		as_dict=True,
	)
