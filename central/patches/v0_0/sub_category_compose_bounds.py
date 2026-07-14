# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Backfill the composed-config bounds onto the VM optimisation-profile sub-categories.

ADR 0009 / issue #81 promote the optimisation profile from a configurator pre-fill
default to a runtime constraint: a numeric `ram_ratio` (replacing the legacy `1:N`
`memory_ratio` string as the source of truth), the allowed `vcpu_steps`, and the disk
range. The seed sets these on fresh profiles; this carries them onto the four VM
profiles that already exist.

`ram_ratio` is derived from the existing `memory_ratio` ("1:4" -> 4) so a hand-edited
ratio survives; the steps/disk bounds fall back to the shipped defaults.

Idempotent: each field is set only when it is still blank.
"""

import frappe

# Default bounds per profile — mirror taxonomy_setup so a backfilled site matches a
# fresh install. ram_ratio here is only a fallback when memory_ratio can't be parsed.
DEFAULTS = {
	"General": {"ram_ratio": 4, "vcpu_steps": "1,2,4,8,16", "disk_min": 10, "disk_max": 2000},
	"CPU Optimised": {"ram_ratio": 2, "vcpu_steps": "1,2,4,8,16,32", "disk_min": 10, "disk_max": 1000},
	"Memory Optimised": {"ram_ratio": 8, "vcpu_steps": "1,2,4,8,16", "disk_min": 10, "disk_max": 2000},
	"Storage Optimised": {"ram_ratio": 8, "vcpu_steps": "1,2,4,8", "disk_min": 100, "disk_max": 10000},
}


def execute():
	for name, defaults in DEFAULTS.items():
		if not frappe.db.exists("Plan Sub-Category", name):
			continue
		current = frappe.db.get_value(
			"Plan Sub-Category",
			name,
			["ram_ratio", "vcpu_steps", "disk_min", "disk_max", "memory_ratio"],
			as_dict=True,
		)
		updates = {}
		if not current.ram_ratio:
			updates["ram_ratio"] = _ratio_from_memory(current.memory_ratio) or defaults["ram_ratio"]
		if not current.vcpu_steps:
			updates["vcpu_steps"] = defaults["vcpu_steps"]
		if not current.disk_min:
			updates["disk_min"] = defaults["disk_min"]
		if not current.disk_max:
			updates["disk_max"] = defaults["disk_max"]
		if updates:
			frappe.db.set_value("Plan Sub-Category", name, updates, update_modified=False)


def _ratio_from_memory(memory_ratio) -> int | None:
	"""'1:4' -> 4; anything unparseable -> None."""
	if not memory_ratio or ":" not in str(memory_ratio):
		return None
	try:
		return int(str(memory_ratio).split(":", 1)[1])
	except ValueError:
		return None
