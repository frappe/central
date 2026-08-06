# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""What the read-only transaction cannot see.

The database refuses writes at any call depth, which is the strong half of the
guarantee. It has no opinion about redis or HTTP, so the side effects that leave by
those routes are held here instead — by a grep, which is crude but is the thing that
will still be working in a year.

`enqueue` is the one that matters most: the job it schedules runs later, on a fresh
and fully writable connection, long after the read-only transaction has closed.
"""

from pathlib import Path

import frappe
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase

BANNED = (
	"publish_realtime",
	"frappe.enqueue",
	"enqueue_doc",
	"sendmail",
	"frappe.db.commit",
)

# Modules whose decision half a projection calls. A ban on the projection package
# alone would prove nothing about what runs three frames down.
GUARDED = (
	"billing/projection",
	"billing/revenue/dunning.py",
	"billing/revenue/invoicing/generate.py",
)


def _sources():
	root = Path(frappe.get_app_path("central"))
	for rel in GUARDED:
		target = root / rel
		if target.is_dir():
			yield from sorted(target.rglob("*.py"))
		else:
			yield target


class TestNoSideEffectsTheDatabaseCannotSee(IntegrationTestCase):
	def test_guarded_modules_reach_neither_redis_nor_the_mail_queue(self):
		offences = []
		for path in _sources():
			source = path.read_text()
			for line_no, line in enumerate(source.splitlines(), start=1):
				code = line.split("#", 1)[0]
				for banned in BANNED:
					if banned in code:
						offences.append(f"{path.name}:{line_no} {banned}")
		self.assertEqual(offences, [], f"side effects outside the transaction: {offences}")

	def test_the_projection_package_imports_no_gateway_adapter(self):
		offences = [
			path.name
			for path in _sources()
			if "billing/projection" in str(path) and "gateways" in path.read_text()
		]
		self.assertEqual(offences, [], "a projection must never reach a payment gateway")
