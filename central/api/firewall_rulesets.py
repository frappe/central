import frappe
from frappe import _
from frappe.query_builder.functions import Count
from frappe.utils.translations import _lt

from central.errors import handle_resource_operation
from central.iam import can, can_on_any_server
from central.infrastructure.doctype.virtual_machine.virtual_machine import VirtualMachine
from central.utils.guards import require_capability


def require_ruleset_manager(team: str) -> None:
	# A ruleset changes every server that uses it, so a grant on one server is not enough.
	if not can(frappe.session.user, team, "server:network"):
		frappe.throw(
			_("You can't change this team's firewall rulesets. Ask a team admin to review your access."),
			frappe.PermissionError,
		)


@frappe.whitelist(methods=["GET"])
def list_firewall_rulesets(team: str) -> list[dict]:
	"""Return the team's rulesets, each with the number of servers that use it."""
	if not can_on_any_server(frappe.session.user, team, "server:view"):
		frappe.throw(_("You can't view this team's firewall rulesets."), frappe.PermissionError)

	rulesets = frappe.get_list(
		"Firewall Ruleset",
		filters={"team": team},
		fields=["name", "title", "rules", "last_sync_error"],
		order_by="title asc",
		limit=0,
	)
	if not rulesets:
		return []

	# Counts every server of the team, also one this user cannot open.
	server = frappe.qb.DocType("Virtual Machine")
	link = frappe.qb.DocType("Server Firewall Ruleset")
	counts = dict(
		frappe.qb.from_(link)
		.join(server)
		.on(server.name == link.parent)
		.select(link.firewall_ruleset, Count(link.parent).distinct())
		.where(link.firewall_ruleset.isin([ruleset.name for ruleset in rulesets]))
		.where(server.status != "Terminated")
		.groupby(link.firewall_ruleset)
		.run()
	)
	for ruleset in rulesets:
		ruleset["rules"] = frappe.parse_json(ruleset["rules"])
		ruleset["server_count"] = counts.get(ruleset["name"], 0)

	return rulesets


@frappe.whitelist(methods=["POST"])
def save_firewall_ruleset(team: str, title: str, rules: dict | str, name: str | None = None) -> str:
	"""Create a ruleset, or change the one in `name`. A change goes to every server that uses it."""
	require_ruleset_manager(team)
	ruleset = _get_team_ruleset(team, name) if name else frappe.new_doc("Firewall Ruleset", team=team)
	ruleset.update({"title": title, "rules": frappe.parse_json(rules)})
	ruleset.save()

	return ruleset.name


@frappe.whitelist(methods=["POST"])
def delete_firewall_ruleset(team: str, name: str) -> None:
	"""Delete a ruleset that no server uses."""
	require_ruleset_manager(team)
	_get_team_ruleset(team, name).delete()


@frappe.whitelist(methods=["POST"])
@handle_resource_operation
@require_capability(
	"server:network",
	_lt("You can't change the network of this server. Ask a team admin to review your access."),
	server="resource_id",
)
def set_server_firewall_rulesets(
	team: str | None = None, resource_id: str | None = None, rulesets: list[str] | str | None = None
) -> None:
	"""Make a server use these team rulesets together. With none, the server keeps the rules
	as its own."""
	server = frappe.get_doc("Virtual Machine", VirtualMachine.get_team_server_name(team, resource_id))
	server.set_firewall_rulesets(frappe.parse_json(rulesets) or [])


def _get_team_ruleset(team: str, name: str):
	ruleset = frappe.get_doc("Firewall Ruleset", name)
	if ruleset.team != team:
		frappe.throw(_("This ruleset does not belong to the team."), frappe.PermissionError)

	return ruleset
