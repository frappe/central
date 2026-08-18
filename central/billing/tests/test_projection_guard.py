# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""A projection cannot write, and the database is what stops it."""

import frappe

from central.billing.projection.guard import (
	ProjectionBoundaryError,
	ProjectionWroteError,
	read_only,
)
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import ensure_team

TEAM = "team-projection-guard"


class TestReadOnlyGuard(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		frappe.db.commit()

	def tearDown(self):
		frappe.db.rollback()

	def test_reads_work_inside_the_guard(self):
		with read_only():
			self.assertTrue(frappe.db.exists("Team", TEAM))

	def test_a_direct_write_is_refused_by_the_database(self):
		with self.assertRaises(ProjectionWroteError):
			with read_only():
				frappe.db.set_value("Team", TEAM, "team_name", "Nope")

	def test_an_insert_is_refused_too(self):
		with self.assertRaises(ProjectionWroteError):
			with read_only():
				frappe.get_doc(
					{
						"doctype": "Credit Ledger Entry",
						"team": TEAM,
						"currency": "INR",
						"amount": 1,
						"entry_type": "Credit",
					}
				).insert(ignore_permissions=True)

	def test_a_write_buried_in_a_callee_is_refused(self):
		# The guarantee has to be transitive: the engine calls into modules that write,
		# so a guard that only inspected the projection package would prove nothing.
		def three_frames_down():
			def deeper():
				frappe.db.set_value("Team", TEAM, "team_name", "Nope")

			deeper()

		with self.assertRaises(ProjectionWroteError):
			with read_only():
				three_frames_down()

	def test_nothing_the_refused_write_touched_survives(self):
		before = frappe.db.get_value("Team", TEAM, "team_name")
		with self.assertRaises(ProjectionWroteError):
			with read_only():
				frappe.db.set_value("Team", TEAM, "team_name", "Nope")
		self.assertEqual(frappe.db.get_value("Team", TEAM, "team_name"), before)

	def test_writing_works_again_afterwards(self):
		with read_only():
			pass
		frappe.db.set_value("Team", TEAM, "team_name", "Fine")
		frappe.db.commit()
		self.assertEqual(frappe.db.get_value("Team", TEAM, "team_name"), "Fine")

	def test_the_flag_is_restored_even_when_a_write_is_refused(self):
		with self.assertRaises(ProjectionWroteError):
			with read_only():
				frappe.db.set_value("Team", TEAM, "team_name", "Nope")
		self.assertFalse(frappe.flags.read_only)

	def test_an_unrelated_error_is_not_disguised_as_a_write(self):
		with self.assertRaises(ZeroDivisionError):
			with read_only():
				1 / 0


class TestTransactionBoundary(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		frappe.db.commit()

	def tearDown(self):
		frappe.db.rollback()

	def test_projecting_mid_transaction_is_refused_rather_than_committing_it(self):
		# Starting a read-only transaction implicitly commits the open one. Asking a
		# question must never decide the fate of somebody else's unfinished work.
		frappe.db.set_value("Team", TEAM, "team_name", "Half done")
		with self.assertRaises(ProjectionBoundaryError):
			with read_only():
				pass

	def test_the_pending_work_is_left_exactly_as_it_was(self):
		frappe.db.set_value("Team", TEAM, "team_name", "Half done")
		with self.assertRaises(ProjectionBoundaryError):
			with read_only():
				pass
		# Neither committed nor discarded — still pending, still the caller's to resolve.
		self.assertEqual(frappe.db.get_value("Team", TEAM, "team_name"), "Half done")
