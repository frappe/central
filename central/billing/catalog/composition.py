# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Composed-config shape validation (ADR 0009, #81).

A custom compute config can only ever be a sane shape: its vCPU is one of the
optimisation profile's allowed steps, its RAM equals vCPU x the profile's ratio,
and its disk sits within the profile's bounds. The optimisation profile
(`Plan Sub-Category`) is promoted here from a configurator pre-fill default to a
runtime constraint.

`validate_composition` is the single authoritative gate, reused by provision (#80)
and resize (#82). Any client-side bounds (#83) are a convenience the server
re-checks here.
"""

import frappe
from frappe import _
from frappe.utils import flt

# The compute primitives a composed config is built from.
COMPUTE = "Compute"
MEMORY = "Memory"
DISK = "Disk"


def parse_vcpu_steps(raw) -> list[float]:
	"""The profile's allowed vCPU values as a sorted list, e.g. '1,2,4,8' -> [1,2,4,8]."""
	if not raw:
		return []
	return sorted({flt(p) for p in str(raw).split(",") if p.strip()})


def composition_quantities(includes) -> dict[str, float]:
	"""Sum a composition (includes rows or dicts) into `{resource_type: quantity}`."""
	out: dict[str, float] = {}
	for row in includes:
		resource_type = row["resource_type"] if isinstance(row, dict) else row.resource_type
		quantity = row["quantity"] if isinstance(row, dict) else row.quantity
		out[resource_type] = out.get(resource_type, 0.0) + flt(quantity)
	return out


def validate_composition(sub_category: str, includes) -> None:
	"""Reject a composed config that is not a valid shape for its profile.

	Each configured constraint is enforced; an unset field (e.g. no disk bounds on a
	profile) places no restriction on that axis. Raises `frappe.ValidationError` with
	a clear message on the first violation.
	"""
	profile = frappe.db.get_value(
		"Plan Sub-Category",
		sub_category,
		["ram_ratio", "vcpu_steps", "disk_min", "disk_max"],
		as_dict=True,
	)
	if not profile:
		frappe.throw(_("Unknown optimisation profile {0}.").format(frappe.bold(sub_category)))

	qty = composition_quantities(includes)
	vcpu = qty.get(COMPUTE, 0.0)
	ram = qty.get(MEMORY, 0.0)
	disk = qty.get(DISK, 0.0)

	steps = parse_vcpu_steps(profile.vcpu_steps)
	if steps and vcpu not in steps:
		frappe.throw(
			_("{0} vCPU is not an allowed step for {1} (allowed: {2}).").format(
				_num(vcpu), sub_category, ", ".join(_num(s) for s in steps)
			)
		)

	if profile.ram_ratio:
		expected = flt(vcpu) * profile.ram_ratio
		if flt(ram) != flt(expected):
			frappe.throw(
				_("{0} requires {1} GB RAM for {2} vCPU (ratio 1:{3}), not {4} GB.").format(
					sub_category, _num(expected), _num(vcpu), profile.ram_ratio, _num(ram)
				)
			)

	if profile.disk_min and disk < profile.disk_min:
		frappe.throw(
			_("Disk {0} GB is below the {1} minimum of {2} GB.").format(
				_num(disk), sub_category, profile.disk_min
			)
		)
	if profile.disk_max and disk > profile.disk_max:
		frappe.throw(
			_("Disk {0} GB exceeds the {1} maximum of {2} GB.").format(
				_num(disk), sub_category, profile.disk_max
			)
		)


def _num(value) -> str:
	"""Trim trailing zeros: 2.0 -> '2', 0.5 -> '0.5'."""
	return f"{flt(value):g}"
