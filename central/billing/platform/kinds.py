# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _

# The billing alert kinds, grouped as the Muted Alerts table offers them. A category
# muted with no alert mutes every kind in it.
CATEGORIES = {
	"Payments": ("failed_webhook", "stale_attempt", "unsettled_capture", "refused_charge", "failed_refund"),
	"Invoicing": ("held_invoice", "failed_accounting_sync"),
	"Dunning": ("suspended_server_running", "termination_due"),
	"Money checks": ("invariant",),
	"Readiness checks": ("readiness",),
}

# A check's option starts with its code, so a reworded check title still matches its mute.
CHECK_SEPARATOR = " · "


def get_alert_options() -> dict[str, list[str]]:
	"""The alerts each category offers: a readable name per kind, or one option per check."""
	options = {}
	for category, kinds in CATEGORIES.items():
		checks = _checks_for(kinds[0])
		if checks is None:
			options[category] = [_kind_label(kind) for kind in kinds]
		else:
			options[category] = [f"{code}{CHECK_SEPARATOR}{title}" for code, (title, _fn) in checks.items()]
	return options


def get_heading(alert: dict) -> str:
	"""The readable name an alert is grouped under: its check with the check's title, or its kind."""
	checks = _checks_for(alert["alert"])
	if checks and alert.get("check") in checks:
		return f"{alert['check']}{CHECK_SEPARATOR}{checks[alert['check']][0]}"
	if any(alert["alert"] in group for group in CATEGORIES.values()):
		return _kind_label(alert["alert"])
	return str(alert["alert"])


def get_check_meaning(kind: str, code: str) -> str:
	"""What a failing check expected, from the first paragraph of its docstring."""
	return "Expected: " + get_first_paragraph(_checks_for(kind)[code][1].__doc__)


def get_first_paragraph(text: str | None) -> str:
	"""The first paragraph of a docstring, on one line."""
	return " ".join((text or "").strip().split("\n\n")[0].split())


def get_muted_keys(rows: list) -> set[str]:
	"""The alert kinds, and the `<kind> <check>` pairs, that the active mute rows silence."""
	keys = set()
	for row in rows:
		kinds = CATEGORIES[row.category]
		if not row.alert:
			keys.update(kinds)
		elif CHECK_SEPARATOR in row.alert:
			keys.add(f"{kinds[0]} {row.alert.split(CHECK_SEPARATOR)[0]}")
		else:
			keys.update(kind for kind in kinds if _kind_label(kind) == row.alert)
	return keys


def is_muted(alert: dict, muted: set[str]) -> bool:
	"""True when the alert's kind is muted, or the one check it reports."""
	return alert["alert"] in muted or f"{alert['alert']} {alert.get('check')}" in muted


def validate_mute(row) -> None:
	"""The row's alert must belong to its category. A check is matched on its code alone."""
	if row.alert and not _is_in_category(row.alert, row.category):
		frappe.throw(
			_("Row {0}: {1} is not an alert in {2}. Choose the alert again.").format(
				row.idx, row.alert, row.category
			),
			title=_("Wrong Alert"),
		)


def _is_in_category(alert: str, category: str) -> bool:
	kinds = CATEGORIES[category]
	checks = _checks_for(kinds[0])
	if checks is None:
		return alert in {_kind_label(kind) for kind in kinds}
	return alert.split(CHECK_SEPARATOR)[0] in checks


def _checks_for(kind: str) -> dict | None:
	"""The check registry behind a check kind, or None for a plain kind."""
	from central.billing.platform import invariants, readiness

	return {"invariant": invariants.CHECKS, "readiness": readiness.CHECKS}.get(kind)


def _kind_label(kind: str) -> str:
	return kind.replace("_", " ").capitalize()
