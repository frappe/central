from unittest.mock import patch

import frappe

from central.billing.tests.e2e import _enter_test_mode
from central.identity.doctype.team.tenant import allocate_tenant_id
from central.integrations.oauth.meta import ROUTE, save_route
from central.tests.utils import ensure_atlas_instance


@frappe.whitelist(allow_guest=True, methods=["POST"])
def seed_route() -> dict:
	"""Test-only, gated on `allow_tests`: a team with one server and site, and a new WABA whose
	Meta webhooks go to that site. Rows are written without hooks, so nothing reaches a region."""
	_enter_test_mode()

	suffix = frappe.generate_hash(length=8)
	team = f"team-e2e-meta-{suffix}"
	frappe.get_doc(
		{
			"doctype": "Team",
			"name": team,
			"team_name": team,
			"owner_user": "Administrator",
			"status": "Active",
			"tenant_id": allocate_tenant_id(),
		}
	).db_insert()
	server = f"server-e2e-meta-{suffix}"
	frappe.get_doc(
		{
			"doctype": "Virtual Machine",
			"name": server,
			"resource_id": server,
			"team": team,
			"region": ensure_atlas_instance("e2e-meta"),
			"status": "Running",
		}
	).db_insert()
	site = f"e2e-meta-{suffix}.localhost"
	frappe.get_doc(
		{"doctype": "Site", "name": site, "site_name": site, "team": team, "server": server}
	).db_insert()
	waba_id = f"waba-e2e-{suffix}"
	save_route(waba_id, team, server, site, frappe.generate_hash())

	frappe.db.commit()
	return {"team": team, "server": server, "site": site, "waba_id": waba_id}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def terminate_server(server: str) -> dict:
	"""Test-only: mark `server` Terminated through its controller. Queued jobs are not sent,
	so no region is called."""
	_enter_test_mode()

	doc = frappe.get_doc("Virtual Machine", server)
	doc.status = "Terminated"
	with patch("frappe.enqueue"):
		doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"status": doc.status}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def get_routed_site(waba_id: str) -> dict:
	"""Test-only: the site that gets the WABA's webhooks, or None."""
	_enter_test_mode()

	return {"site": frappe.db.get_value(ROUTE, waba_id, "site")}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def teardown(team: str) -> dict:
	"""Delete what `seed_route` made. Safe to repeat."""
	_enter_test_mode()

	for doctype in (ROUTE, "Site", "Virtual Machine", "Team"):
		frappe.db.delete(doctype, {"name" if doctype == "Team" else "team": team})
	frappe.db.commit()
	return {"ok": True}
