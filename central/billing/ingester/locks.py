# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""A lock held until the current transaction ends, so one job runs per subject."""

import frappe
from redis.exceptions import LockError

# Longest one step may hold its lock: a remote request at its timeout, and room.
LOCK_SECONDS = 5 * 60


def lock_name(key: str) -> str:
	return frappe.cache.make_key(key)


def hold_until_transaction_ends(key: str) -> bool:
	"""Take the lock for `key`, released once this transaction commits or rolls back.

	Taken before anything is read, so whoever gets it next sees what this one wrote.
	The timeout frees it if the worker dies first.
	"""
	lock = frappe.cache.lock(lock_name(key), timeout=LOCK_SECONDS)
	if not lock.acquire(blocking=False):
		return False

	def release():
		try:
			lock.release()
		except LockError:
			pass  # it outlived its timeout; nothing left to release

	frappe.db.after_commit.add(release)
	frappe.db.after_rollback.add(release)
	return True
