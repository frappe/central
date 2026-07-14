# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Widen the VM profiles' vCPU ladder to the configurator's full set.

The composed-config slider snaps vCPU to the profile's `vcpu_steps`. The first cut
(v23) seeded a narrow integer ladder (1,2,4,8,…); the design needs the configurator's
fractional vCPUs too (1/8, 1/4, 1/2) so a micro config is reachable. This widens the
shipped VM profiles to the full ladder.

Idempotent + non-destructive: only profiles still on a narrow (fraction-less) ladder
are widened, so an admin's custom step set is left alone.
"""

import frappe

from central.billing.catalog.taxonomy_setup import VCPU_LADDER

VM_PROFILES = ("General", "CPU Optimised", "Memory Optimised", "Storage Optimised")


def execute():
	for name in VM_PROFILES:
		current = frappe.db.get_value("Plan Sub-Category", name, "vcpu_steps") or ""
		# Already widened (carries a fractional rung) or hand-customised → leave it.
		if "0.125" in current:
			continue
		if name and frappe.db.exists("Plan Sub-Category", name):
			frappe.db.set_value("Plan Sub-Category", name, "vcpu_steps", VCPU_LADDER, update_modified=False)
