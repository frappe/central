# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe

_SAVEPOINT = "billing_job_item"


def each_isolated(job: str, doctype: str, names, work) -> list:
	"""Run `work(name)` for every name, so one bad row never stops the rest.

	1. Each item runs under a savepoint and commits on its own, so the next day's run
	   does not start again at the same broken row with everything after it undone.
	2. A failure undoes only that item, leaves an Error Log row naming it, and the job
	   moves on. The results hold only the items that succeeded.
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
			continue
		if not frappe.in_test:
			# The per-row boundary is the point: the next row's failure must not undo this one,
			# and the row locks this item took are released now, not at the end of the run.
			frappe.db.commit()  # nosemgrep: frappe-manual-commit -- one row, one transaction
	return results


def _undo_item() -> None:
	try:
		frappe.db.rollback(save_point=_SAVEPOINT)
	except Exception:
		frappe.db.rollback()
