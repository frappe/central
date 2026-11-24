import frappe
from frappe import _

from central.billing.catalog.server_plans import get_server_plans
from central.billing.catalog.subscriptions import (
	_plan_resize,
	_require_offered_plan,
	create_subscription,
	get_plan_shape,
	resize_to_plan,
)
from central.billing.doctype.billing_profile.billing_profile import get_team_currency
from central.resource_actions import validate_purchase
from central.utils.units import gigabytes_to_mebibytes, vcpus_to_millicores


def get_size_plan(team: str, region: str, size: str, server: str | None = None) -> str:
	"""The server plan titled `size` that the team may buy in the region, as the server plan list offers it.
	For the app's existing `server`, the catalog is the resize one, so its own subscription leaves room for its plan."""
	if server:
		subscription = frappe.db.get_value("Subscription", {"server_id": server}, "name")
		catalog = get_server_plans(team, cluster=region, exclude_subscription=subscription, for_resize=1)
	else:
		catalog = get_server_plans(team, cluster=region)
	plans = [row["plan"] for rows in catalog["plans"].values() for row in rows if row["title"] == size]
	if len(plans) > 1:
		frappe.throw(_("More than one plan is titled {0}. An operator must rename one.").format(size))
	if not plans:
		titles = sorted({row["title"] for rows in catalog["plans"].values() for row in rows})
		frappe.throw(
			_("Size {0} is not available in {1}. Choose one of: {2}.").format(size, region, ", ".join(titles))
		)
	return plans[0]


def get_plan_specs(plan: str) -> dict[str, int]:
	"""The plan's size in Atlas units."""
	shape = get_plan_shape(plan)
	return {
		"cpu_millicores": vcpus_to_millicores(shape["vcpus"]),
		"memory_mib": shape["memory_megabytes"],
		"disk_mib": gigabytes_to_mebibytes(shape["disk_gigabytes"]),
	}


def validate_vm_purchase(team: str, region: str, plan: str) -> float:
	"""Run the checks a new server on `plan` passes, and return its monthly rate."""
	return validate_purchase(team, region, plan, None, None)[1]


def open_vm_subscription(server: str, team: str, region: str, plan: str, rate: float | None) -> None:
	"""Bill the deploy VM from the rate accepted before Atlas created it. A VM found again keeps its subscription."""
	if frappe.db.exists("Subscription", {"server_id": server}):
		return

	create_subscription(
		team,
		region,
		plan=plan,
		resource_id=server,
		opening_quote=(rate, get_team_currency(team)) if rate is not None else None,
	)


def validate_vm_resize(server: str, plan: str) -> None:
	"""Run the checks a server moving to `plan` passes (offered, headroom, a way to pay), before the VM stops."""
	subscription = frappe.get_doc("Subscription", {"server_id": server})
	machine = frappe.get_doc("Virtual Machine", server)
	_require_offered_plan(subscription, plan, machine.region)
	_plan_resize(subscription, machine, plan, None, None)


def update_vm_plan(server: str, plan: str) -> None:
	"""Bill the VM at `plan` once it runs at that size. Nothing changes while the plan is the same."""
	subscription = frappe.db.get_value("Subscription", {"server_id": server}, "name")
	resize_to_plan(subscription, plan)
	# The VM's plan is what its subscription follows each time Central sees it running.
	frappe.db.set_value("Virtual Machine", server, "plan", plan)
