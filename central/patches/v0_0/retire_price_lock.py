# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Retire the Price Lock doctype — the Subscription Change ledger is the only lock now.

ADR 0010 folded the price-lock into the `Subscription Change` ledger, but only the
write path moved; `Price Lock` lingered as a parallel read source until #86 migrated
every reader onto the ledger. This patch closes it out: it backfills any remaining
open `Price Lock` whose resource's subscription lacks an open billing segment (legacy
agent-era locks — provisioning long dual-wrote, so most already have one), then drops
the `Price Lock` doctype and its table.

Idempotent: the backfill writes a segment only where one is missing, and the drop is
guarded on the doctype still existing.
"""

import frappe

# The rate-bearing Subscription Change types that bound an open billing segment.
_SEGMENT_TYPES = ["Created", "Plan Changed", "Cancelled"]


def execute():
	backfill_open_locks_into_ledger()
	_drop_price_lock_doctype()


def backfill_open_locks_into_ledger(locks=None) -> int:
	"""Ensure every resource that held an open `Price Lock` has an open segment on the
	`Subscription Change` ledger (ADR 0010). Returns how many segments were written.

	`locks` is injectable (a list of lock dicts) so the mapping is testable after the
	doctype is dropped; left None, it reads the live open locks."""
	if locks is None:
		if not frappe.db.table_exists("Price Lock"):
			return 0
		locks = frappe.get_all(
			"Price Lock",
			filters={"ended_at": ["is", "not set"]},
			fields=["resource_id", "team", "plan", "currency", "locked_rate", "started_at"],
		)
	return sum(1 for lock in locks if _ensure_segment_for_lock(lock))


def _ensure_segment_for_lock(lock) -> bool:
	"""Write a `Created` segment mirroring `lock` when its resource's subscription has
	no open segment. A no-op when the subscription is missing or already open."""
	subscription = frappe.db.get_value("Subscription", {"asset_id": lock.get("resource_id")}, "name")
	if not subscription:
		return False

	latest = frappe.get_all(
		"Subscription Change",
		filters={"subscription": subscription, "change_type": ["in", _SEGMENT_TYPES]},
		fields=["change_type"],
		order_by="effective_at desc, creation desc",
		limit=1,
	)
	if latest and latest[0].change_type != "Cancelled":
		return False  # already has an open segment

	frappe.get_doc(
		{
			"doctype": "Subscription Change",
			"subscription": subscription,
			"change_type": "Created",
			"new_value": lock.get("plan"),
			"locked_rate": lock.get("locked_rate"),
			"currency": lock.get("currency"),
			"effective_at": lock.get("started_at") or frappe.utils.now_datetime(),
		}
	).insert(ignore_permissions=True)
	return True


def _drop_price_lock_doctype():
	if frappe.db.exists("DocType", "Price Lock"):
		frappe.delete_doc("DocType", "Price Lock", force=True, ignore_permissions=True)
	# delete_doc can leave the physical table behind when the doctype JSON is already
	# gone; drop it explicitly so no orphan `tabPrice Lock` lingers.
	if frappe.db.table_exists("Price Lock"):
		frappe.db.sql_ddl("DROP TABLE IF EXISTS `tabPrice Lock`")
	frappe.db.commit()
