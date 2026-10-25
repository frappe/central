# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe

_SAVEPOINT = "billing_job_item"


def each_isolated(job: str, doctype: str, names, work) -> list:
	"""Run `work(name)` for every name, so one bad row never stops the rest.

	1. Each item runs under a savepoint and commits on its own, so the next day's run
	   does not start again at the same broken row with everything after it undone.
	2. A failure undoes only that item, leaves an Error Log row naming it, and the job
	   moves on. Its result is `{"name": name, "failed": True}`.
	3. An item that committed part-way (a gateway call commits its intent first) has no
	   savepoint left; everything since the last per-item commit is that item's, so the
	   whole transaction is rolled back instead.
	"""
	results = []
	for name in names:
		frappe.db.savepoint(_SAVEPOINT)
		try:
			results.append(work(name))
		except Exception:
			_undo_item()
			frappe.log_error(
				title=f"{job} failed on {doctype} {name}", reference_doctype=doctype, reference_name=name
			)
			results.append({"name": name, "failed": True})
			continue
		if not frappe.in_test:
			frappe.db.commit()
	return results


def _undo_item() -> None:
	try:
		frappe.db.rollback(save_point=_SAVEPOINT)
	except Exception:
		frappe.db.rollback()
