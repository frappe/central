# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.report import _paging


class TestReportRowCap(IntegrationTestCase):
	def test_a_long_report_shows_the_first_rows_and_says_so(self):
		with patch.object(_paging, "ROW_LIMIT", 3):
			rows, message = _paging.first_rows(list(range(5)), "Note")
		self.assertEqual(rows, [0, 1, 2])
		self.assertIn("first 3 of 5", message)
		self.assertTrue(message.startswith("Note"))

	def test_a_short_report_is_left_alone(self):
		self.assertEqual(_paging.first_rows([1, 2], None), ([1, 2], None))

	def test_an_export_gets_every_row(self):
		with (
			patch.object(_paging, "ROW_LIMIT", 3),
			patch.dict(frappe.form_dict, {"cmd": "frappe.desk.query_report.export_query"}),
		):
			rows, _message = _paging.first_rows(list(range(5)))
		self.assertEqual(len(rows), 5)
