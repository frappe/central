# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Component rate card — authored by the Plan Configurator (ADR 0011).

The composed-config primitives (`Compute`, `Memory`, `Disk`) are each priced per
unit on the *same* `Catalog Rate` spine as offerings (`priced_doctype = Resource
Type`). ADR 0011 makes the Plan Configurator the single authority that writes them,
folding the old standalone `update_component_rate` endpoint into the Configurator's
internal write and demoting the seed to fresh-install defaults only.

The value this module adds over a raw setter is *completeness*: a composed config is
sellable in a currency/region only when **every** primitive is priced there
(`resolve_config_rate` returns None otherwise — the cause of the historical `$0`
estimate). These helpers make that gap visible at authoring time, and flag a preset
whose flat rate diverges from its component sum.
"""

import frappe
from frappe import _
from frappe.utils import flt

from central.billing.catalog.pricing import (
	get_catalog_rates,
	resolve_component_rate,
	resolve_config_rate,
	resolve_rate,
	set_catalog_rate,
)
from central.billing.catalog.rate_card import COMPONENT_UNITS

# The composable primitives a component card must price for a config to be sellable.
COMPONENT_RESOURCE_TYPES = tuple(COMPONENT_UNITS)


def set_component_rate(resource_type: str, currency: str, rate, cluster: str | None = None) -> dict:
	"""Write one `Resource Type`'s per-unit `Catalog Rate` — the Configurator's internal
	component-card write (ADR 0011). A single-document upsert: it mints no plans, and a
	running composed config keeps billing its locked config rate (#80/#82)."""
	if not frappe.db.exists("Resource Type", resource_type):
		frappe.throw(_("Resource Type {0} does not exist.").format(frappe.bold(resource_type)))
	cluster = (cluster or "").strip() or None
	set_catalog_rate("Resource Type", resource_type, currency, rate, cluster=cluster)
	return {
		"resource_type": resource_type,
		"currency": currency,
		"cluster": cluster or "global",
		"rate": flt(rate),
	}


def component_card_gaps(currency: str, cluster: str | None = None) -> list[str]:
	"""The composable primitives with no rate for `(currency, cluster)` — an incomplete
	card. Empty means a composed config can be fully priced (and so offered) there."""
	return [
		rt
		for rt in COMPONENT_RESOURCE_TYPES
		if resolve_component_rate(rt, currency, cluster) is None
	]


def is_component_card_complete(currency: str, cluster: str | None = None) -> bool:
	"""True when every composable primitive is priced for `(currency, cluster)`."""
	return not component_card_gaps(currency, cluster)


def preset_component_warning(plan: str, currency: str, cluster: str | None = None) -> dict | None:
	"""Compare a preset's flat rate to the sum of its composition at the component card.

	Returns None when the two agree (or the comparison can't be made — the preset or the
	card isn't priced for this currency/cluster). Otherwise a dict describing the
	divergence: `below` (flat < components — an intended bundle discount) or `above`
	(flat > components — a likely mispricing), with both numbers (ADR 0011)."""
	flat = resolve_rate(get_catalog_rates("Plan", plan), currency, cluster)
	if flat is None:
		return None
	includes = frappe.get_all(
		"Plan Includes", filters={"parent": plan}, fields=["resource_type", "quantity"]
	)
	component_sum = resolve_config_rate(includes, currency, cluster)
	if component_sum is None:
		return None  # card incomplete for this composition — a gap, surfaced separately

	flat, component_sum = flt(flat, 2), flt(component_sum, 2)
	if flat == component_sum:
		return None
	return {
		"plan": plan,
		"currency": currency,
		"cluster": cluster or "global",
		"flat_rate": flat,
		"component_sum": component_sum,
		"kind": "below" if flat < component_sum else "above",
	}
