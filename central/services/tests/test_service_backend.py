# Copyright (c) 2026, frappe and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from central.services.api.ops import _get_or_create_backend


def _ensure_llm_service():
	if not frappe.db.exists("Add-on Service", "llm"):
		frappe.get_doc(
			{
				"doctype": "Add-on Service",
				"service_key": "llm",
				"title": "LLM Hosting",
				"handler_key": "grove",
				"plan_category": "AI Tokens",
				"is_active": 1,
			}
		).insert(ignore_permissions=True)


class TestServiceBackendRegister(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		_ensure_llm_service()
		frappe.db.delete("Service Backend", {"service": "llm"})

	def test_reregister_with_null_region_does_not_duplicate(self):
		# Regression: the lookup filtered region="" but the insert stored NULL, and
		# NULL <> "" in MariaDB, so every re-register created a fresh backend row and
		# downstream resolution became non-deterministic. region must normalise to ""
		# on write so a second register resolves to the same row.
		first = _get_or_create_backend("llm", "http://grove.localhost:8001", None)
		self.assertEqual(first.region, "")

		second = _get_or_create_backend("llm", "http://grove.localhost:8002", None)
		self.assertEqual(second.name, first.name)

		rows = frappe.get_all("Service Backend", {"service": "llm"}, pluck="name")
		self.assertEqual(len(rows), 1)
