# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Recording what a projection read, so a later one can be replayed against it.

The obvious regression harness does not work. Snapshot the book, deploy, re-run, diff —
and the two runs happen at different times with the data moved in between. Teams resize,
top up, get invoiced and pay, and every one of those legitimately changes the projection.
The diff drowns in deltas nobody can attribute to the deploy, and an unattributable diff
is ignored within a fortnight.

So stop diffing across *time* and diff across *code with the inputs held fixed*. A thin
recorder captures every `(query → result)` the engine consumed; the cassette is stored
with the answer; after the deploy the new code is replayed **against the cassette**
rather than the database. Inputs are then bit-identical by construction and every
surviving delta is attributable.

A read the new code makes that is *absent* from the cassette is itself worth reporting —
the rating path now consults something it did not before, which is a change worth knowing
about even when the number is unmoved.

The seam sits at the database layer, underneath the state/reference split, so nothing
needs threading through `resolve_tax` and its neighbours.
"""

import hashlib
import json

import frappe


class Recorder:
	"""Captures every read a projection makes, keyed so replay is deterministic."""

	def __init__(self):
		self.entries: dict[str, list] = {}
		self.order: list[str] = []

	def record(self, key: str, value):
		self.entries.setdefault(key, []).append(value)
		self.order.append(key)

	def cassette(self) -> dict:
		return {"entries": self.entries, "reads": len(self.order)}


class Replay:
	"""Answers reads from a cassette, and reports any the recording never saw."""

	def __init__(self, cassette: dict):
		self.entries = {k: list(v) for k, v in (cassette or {}).get("entries", {}).items()}
		self.missing: list[str] = []

	def answer(self, key: str, default=None):
		queue = self.entries.get(key)
		if not queue:
			# Not an error. The code now reads something the recording did not, which is
			# a finding in its own right — it is why the number moved, or why it did not.
			self.missing.append(key)
			return default
		# Reads repeat within a projection; replay them in the order they were captured.
		return queue.pop(0) if len(queue) > 1 else queue[0]


def key(*parts) -> str:
	"""A stable key for one read. Order matters; formatting must not."""
	blob = json.dumps(parts, sort_keys=True, default=str)
	return hashlib.sha1(blob.encode()).hexdigest()[:16]


def diff(before: dict, after: dict, ignore: tuple = ("as_of",)) -> list[dict]:
	"""Every field that moved between two projections of the same thing.

	Walks both structures rather than comparing totals: a total that happens to match
	while two lines moved in opposite directions is exactly the regression a summary
	comparison would miss.
	"""
	found: list[dict] = []
	_walk(before, after, "", found, set(ignore))
	return found


def _walk(before, after, path: str, found: list, ignore: set):
	if isinstance(before, dict) and isinstance(after, dict):
		for field in sorted(set(before) | set(after)):
			if field in ignore:
				continue
			_walk(before.get(field), after.get(field), f"{path}.{field}" if path else field, found, ignore)
		return

	if isinstance(before, list) and isinstance(after, list):
		if len(before) != len(after):
			found.append({"path": path, "before": f"{len(before)} items", "after": f"{len(after)} items"})
			return
		for i, (b, a) in enumerate(zip(before, after, strict=False)):
			_walk(b, a, f"{path}[{i}]", found, ignore)
		return

	if _differs(before, after):
		found.append({"path": path, "before": before, "after": after})


def _differs(before, after) -> bool:
	if isinstance(before, int | float) and isinstance(after, int | float):
		# Money is float; a representation wobble is not a regression.
		return abs(frappe.utils.flt(before) - frappe.utils.flt(after)) > 0.005
	return before != after


def report(before: dict, after: dict, replay: Replay | None = None) -> dict:
	"""What changed, and whether the new code read anything the recording lacks."""
	changes = diff(before, after)
	return {
		"changed": bool(changes),
		"differences": changes,
		# Ranked by how much money moved, so the worst is read first.
		"worst": max(
			(c for c in changes if isinstance(c.get("before"), int | float)),
			key=lambda c: abs(frappe.utils.flt(c["after"]) - frappe.utils.flt(c["before"])),
			default=None,
		),
		"reads_absent_from_the_cassette": len(replay.missing) if replay else 0,
	}
