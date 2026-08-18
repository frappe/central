# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt
"""Shared last-writer-wins upsert for the read-only Atlas mirrors (Asset, Site).

Both are written only by the integration layer from Atlas events / reconcile, and
both carried comment-for-comment identical upsert-with-duplicate-recovery. The
doctype-specific field mapping stays in each controller's ``_stamp``; this owns the
exists → insert → lock → LWW → race-recovery flow that was duplicated.
"""

from __future__ import annotations

from collections.abc import Callable

import frappe
from frappe.utils import get_datetime


def upsert_mirror(
	doctype: str,
	name: str | None,
	team: str | None,
	occurred_at,
	stamp: Callable[[object], None],
) -> None:
	"""Upsert one mirrored resource. ``stamp`` writes the doctype's fields onto the
	doc (a closure over the event payload). A row with no name/team, or a team that
	is not a real Team, belongs to no mirror and is skipped. ``occurred_at`` (event
	push) drives last-writer-wins; freshness stamping lives inside ``stamp``."""
	if not name or not team or not frappe.db.exists("Team", team):
		return
	if frappe.db.exists(doctype, name):
		_apply(doctype, name, occurred_at, stamp)
		return
	try:
		doc = frappe.new_doc(doctype)
		stamp(doc)
		# Users can't write the mirror; the verified Atlas event/pull authorizes it,
		# not desk RBAC.
		doc.save(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		# Lost the insert race: under REPEATABLE READ our exists-check ran on a
		# snapshot that predated a concurrent writer's commit, so we took the insert
		# path and hit the unique key. Recover as an update.
		_apply(doctype, name, occurred_at, stamp)


def _apply(doctype: str, name: str, occurred_at, stamp: Callable[[object], None]) -> None:
	# Lock + load in one current read. A plain get_doc after a stale snapshot can
	# miss a row another writer just committed (DoesNotExistError) or load a stale
	# `modified` (TimestampMismatchError against a concurrent save).
	doc = frappe.get_doc(doctype, name, for_update=True)
	# Last-writer-wins: an event older than what we've already applied is dropped.
	if occurred_at and doc.last_event_at and get_datetime(doc.last_event_at) > get_datetime(occurred_at):
		return
	stamp(doc)
	doc.save(ignore_permissions=True)
