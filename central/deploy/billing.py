import frappe

from central.billing.catalog.composition import COMPUTE, DISK, MEMORY, validate_composition
from central.billing.catalog.subscriptions import (
	_plan_resize,
	create_subscription,
	resize_composed_subscription,
)
from central.billing.doctype.billing_profile.billing_profile import get_team_currency
from central.resource_actions import validate_purchase
from central.utils.units import mebibytes_to_gigabytes, millicores_to_vcpus


def get_composition(specs: dict[str, int]) -> list[dict]:
	"""A deploy VM's shape as the composition a custom-size server is billed by."""
	return [
		{"resource_type": COMPUTE, "quantity": millicores_to_vcpus(specs["cpu_millicores"])},
		{"resource_type": MEMORY, "quantity": mebibytes_to_gigabytes(specs["memory_mib"])},
		{"resource_type": DISK, "quantity": mebibytes_to_gigabytes(specs["disk_mib"])},
	]


def validate_vm_purchase(team: str, region: str, specs: dict[str, int], profile: str) -> float:
	"""Run the checks a new custom-size server passes, and return its monthly rate."""
	_composition, rate = validate_purchase(team, region, None, get_composition(specs), profile)
	return rate


def open_vm_subscription(
	server: str, team: str, region: str, specs: dict[str, int], profile: str, rate: float | None
) -> None:
	"""Bill the deploy VM from the rate accepted before Atlas created it. A VM found again keeps its subscription."""
	if frappe.db.exists("Subscription", {"server_id": server}):
		return

	create_subscription(
		team,
		region,
		resource_id=server,
		pricing_mode="Composed",
		includes=get_composition(specs),
		sub_category=profile,
		opening_quote=(rate, get_team_currency(team)) if rate is not None else None,
	)


def validate_vm_resize(server: str, specs: dict[str, int], profile: str) -> None:
	"""Run the checks a server resize passes (shape, headroom, a way to pay), before the VM stops."""
	composition = get_composition(specs)
	validate_composition(profile, composition)
	subscription = frappe.get_doc("Subscription", {"server_id": server})
	_plan_resize(subscription, frappe.get_doc("Virtual Machine", server), None, composition, profile)


def update_vm_subscription(server: str, specs: dict[str, int], profile: str) -> None:
	"""Re-price the subscription to the VM's size. Nothing changes while the size is the same."""
	subscription = frappe.db.get_value("Subscription", {"server_id": server}, "name")
	resize_composed_subscription(subscription, get_composition(specs), profile)
