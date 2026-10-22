from unittest.mock import patch

import frappe
from frappe.utils import add_days, nowdate

from central.billing.catalog.server_plans import get_server_plans
from central.billing.revenue import credits
from central.billing.states import transition
from central.billing.tests.e2e import _enter_test_mode
from central.infrastructure.doctype.site.plan_change import PlanChange
from central.site_provisioning import get_cheapest_trial_plan, trial_regions


@frappe.whitelist(allow_guest=True, methods=["POST"])
def seed_server(team: str, trial_state: str = "Active", days_left: int = 5, status: str = "Running") -> dict:
	"""Test-only, gated on `allow_tests`: give `team` a running server with one site, the way a
	signup trial leaves it. `trial_state` is Active, Ended, or empty for a server the team bought
	directly in the console. Rows are written without hooks, so nothing reaches a region."""
	_enter_test_mode()

	region, plan = _trial_region_and_plan(team)
	server = _insert_server(team, region, plan, status)
	audience = f"pilot-e2e-{frappe.generate_hash(length=8)}"
	frappe.get_doc(
		{
			"doctype": "Pilot Credential",
			"pilot_credential_id": audience,
			"team": team,
			"server": server.name,
			"audience_id": audience,
			"status": "Active",
		}
	).db_insert()
	site = _insert_site(team, server.name, trial_state, days_left)
	if not trial_state:
		server.ensure_subscription_enabled()

	frappe.db.commit()
	return {"server": server.name, "site": site, "audience": audience, "region": region, "plan": plan}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def add_payment_method(team: str) -> dict:
	"""Activate a card for `team`, as a gateway confirmation does. The real hook grants the welcome
	credit and converts the trials. The conversion's power job is not sent, so no region is called."""
	_enter_test_mode()

	method = frappe.get_doc(
		{
			"doctype": "Payment Method",
			"team": team,
			"gateway": _gateway(),
			"method_type": "Card",
			"status": "Pending Validation",
			"is_default": 1,
		}
	).insert(ignore_permissions=True)
	with patch("frappe.enqueue"):
		transition(method, "Active")
		method.save(ignore_permissions=True)

	frappe.db.commit()
	return {"balance": credits.get_balance(team)["balance"]}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def queue_plan_change(team: str, server: str, site: str, status: str = "In Progress") -> dict:
	"""A resize of the site's server in `status`, and the signed link to its progress page."""
	_enter_test_mode()

	region = frappe.db.get_value("Virtual Machine", server, "region")
	# Written without hooks, so no worker dispatches the resize to a region.
	action = frappe.get_doc(
		{
			"doctype": "Resource Action",
			"name": frappe.generate_hash(length=10),
			"resource_type": "Server",
			"action": "resize",
			"team": team,
			"region": region,
			"title": server,
			"server": server,
			"resource_id": server,
			"requested_by": "Administrator",
			"correlation_id": frappe.generate_hash(length=32),
			"status": status,
			"request_payload": frappe.as_json(
				{
					"subscription": "e2e-subscription",
					"plan": None,
					"shape": {"vcpus": 2.0, "memory_megabytes": 4096, "disk_gigabytes": 40},
					"from_plan": frappe.db.get_value("Virtual Machine", server, "plan"),
					"from_shape": {"vcpus": 1.0, "memory_megabytes": 2048, "disk_gigabytes": 25},
				}
			),
		}
	)
	action.db_insert()
	frappe.db.commit()
	return {"action": action.name, "url": PlanChange(frappe.get_doc("Site", site), action).url}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def set_action_status(action: str, status: str) -> dict:
	_enter_test_mode()

	frappe.db.set_value("Resource Action", action, "status", status)
	frappe.db.commit()
	return {"status": status}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def teardown_servers(team: str) -> dict:
	"""Delete what `seed_server` and `queue_plan_change` made. Safe to repeat."""
	_enter_test_mode()

	for doctype in ("Resource Action", "Site", "Pilot Credential", "Subscription", "Virtual Machine"):
		frappe.db.delete(doctype, {"team": team})
	frappe.db.commit()
	return {"ok": True}


def _trial_region_and_plan(team: str) -> tuple[str, str]:
	"""Central's own trial region and plan. A site with no plan marked Available on Trial falls back
	to the cheapest plan of a region that serves sites."""
	for region in trial_regions():
		plan = get_cheapest_trial_plan(team, region)
		if plan:
			return region, plan
	for region in trial_regions():
		plans = [row for rows in get_server_plans(team, cluster=region)["plans"].values() for row in rows]
		if plans:
			return region, min(plans, key=lambda plan: plan["rate"])["plan"]
	frappe.throw("No region on this site offers a plan for this team.")


def _insert_server(team: str, region: str, plan: str, status: str):
	name = f"server-e2e-{frappe.generate_hash(length=8)}"
	server = frappe.get_doc(
		{
			"doctype": "Virtual Machine",
			"name": name,
			"resource_id": name,
			"team": team,
			"region": region,
			"title": "e2e-trial",
			"status": status,
			"plan": plan,
			"vcpus": 1,
			"memory_megabytes": 2048,
			"disk_gigabytes": 25,
			"atlas_vm_id": f"vm-{name}",
		}
	)
	server.db_insert()
	return server


def _insert_site(team: str, server: str, trial_state: str, days_left: int) -> str:
	# A .localhost name fails a ping at once; an unknown domain can hang in DNS.
	name = f"e2e-{frappe.generate_hash(length=8)}.localhost"
	frappe.get_doc(
		{
			"doctype": "Site",
			"name": name,
			"site_name": name,
			"team": team,
			"server": server,
			"trial_state": trial_state or None,
			"trial_ends_on": add_days(nowdate(), days_left) if trial_state else None,
			"trial_deletes_on": add_days(nowdate(), days_left + 7) if trial_state else None,
		}
	).db_insert()
	return name


def _gateway() -> str:
	return frappe.get_all("Payment Gateway", pluck="name", order_by="name asc", limit=1)[0]
