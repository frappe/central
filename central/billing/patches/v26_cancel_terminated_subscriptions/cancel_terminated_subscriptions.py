# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Close the billing segment for subscriptions whose VM is already Terminated.

Until now termination only disabled the subscription (enabled=0) — it never recorded
a `Cancelled` Subscription Change, so the open billing segment stayed open (ADR 0010).
A terminated VM therefore kept counting toward its team's run-rate and consumed its
trust-tier headroom (blocking new VMs). The Asset controller now cancels on
termination; this backfills the ones terminated before that fix.

For every Subscription whose Asset is Terminated but whose latest segment is still
open (Created / Plan Changed), append a `Cancelled` change to close it, and disable
the subscription if it somehow wasn't. Idempotent: a subscription already closed
(latest segment Cancelled) or without a segment is skipped, so re-running is a no-op.
"""

import frappe

# The rate-bearing Subscription Change types that bound an open billing segment.
_SEGMENT_TYPES = ["Created", "Plan Changed", "Cancelled"]


def execute():
	fixed = cancel_terminated_subscriptions()
	if fixed:
		frappe.logger("patches").info(f"v26: cancelled {fixed} terminated-but-open subscription(s)")


def cancel_terminated_subscriptions() -> int:
	"""Close the open segment of every subscription on a Terminated Asset. Returns the
	number of segments closed."""
	terminated_assets = frappe.get_all("Asset", filters={"status": "Terminated"}, pluck="name")
	if not terminated_assets:
		return 0

	subs = frappe.get_all(
		"Subscription", filters={"asset_id": ["in", terminated_assets]}, fields=["name", "enabled"]
	)
	if not subs:
		return 0

	latest = _latest_segment_types([s.name for s in subs])
	fixed = 0
	for s in subs:
		# An open segment on a terminated VM is the bug — close it. (None = never had a
		# segment; nothing to close.)
		if latest.get(s.name) not in (None, "Cancelled"):
			_append_cancelled(s.name)
			fixed += 1
		if s.enabled:
			frappe.db.set_value("Subscription", s.name, "enabled", 0)
	frappe.db.commit()
	return fixed


def _latest_segment_types(subscription_names: list[str]) -> dict[str, str]:
	"""subscription -> its most-recent rate-bearing change type, in one batched query."""
	rows = frappe.get_all(
		"Subscription Change",
		filters={"subscription": ["in", subscription_names], "change_type": ["in", _SEGMENT_TYPES]},
		fields=["subscription", "change_type"],
		order_by="effective_at desc, creation desc",
	)
	latest: dict[str, str] = {}
	for r in rows:
		latest.setdefault(r.subscription, r.change_type)
	return latest


def _append_cancelled(subscription: str) -> None:
	frappe.get_doc(
		{
			"doctype": "Subscription Change",
			"subscription": subscription,
			"change_type": "Cancelled",
			"effective_at": frappe.utils.now_datetime(),
			"changed_by": "Administrator",
		}
	).insert(ignore_permissions=True)
