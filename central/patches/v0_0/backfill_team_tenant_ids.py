import frappe
from frappe import _

from central.central.doctype.team.team import on_doctype_update
from central.central.doctype.team.tenant import (
	allocate_tenant_id,
	prepare_tenant_id_series,
	validate_tenant_id,
)


def execute() -> None:
	teams = frappe.get_all("Team", fields=["name", "tenant_id"], order_by="name")
	validate_existing_mappings(teams)
	missing = [team.name for team in teams if not team.tenant_id]
	validate_unassigned_teams(missing)
	prepare_tenant_id_series()
	for name in missing:
		frappe.db.set_value("Team", name, "tenant_id", allocate_tenant_id(), update_modified=False)
	on_doctype_update()


def validate_existing_mappings(teams: list[frappe._dict]) -> None:
	seen = set()
	for team in teams:
		if not team.tenant_id:
			continue
		validate_tenant_id(team.tenant_id)
		if team.tenant_id in seen:
			frappe.throw(
				_("Duplicate Team tenant ID {0}. Resolve ownership before migration.").format(team.tenant_id)
			)
		seen.add(team.tenant_id)


def validate_unassigned_teams(teams: list[str]) -> None:
	if not teams:
		return
	for doctype in ("Asset", "Site"):
		resources = frappe.get_all(
			doctype,
			filters={"team": ["in", teams], "status": ["!=", "Terminated"]},
			fields=["name", "team"],
			limit=1,
		)
		if resources:
			resource = resources[0]
			frappe.throw(
				_("Verify the tenant ID for Team {0}, which owns {1} {2}, before migration.").format(
					resource.team, doctype, resource.name
				)
			)
