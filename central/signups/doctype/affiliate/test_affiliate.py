# Copyright (c) 2026, frappe and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api.affiliates import apply, get_affiliate
from central.signups.doctype.affiliate.affiliate import (
	CODE_ALPHABET,
	CODE_LENGTH,
	Affiliate,
	AffiliateStatusError,
	generate_affiliate_code,
)
from central.tests.test_iam import ensure_user

AFFILIATE_DOCTYPES = ("Affiliate", "Affiliate Visit", "Product Referral")


def make_affiliate(email: str, **values) -> "frappe.Document":
	return frappe.get_doc({"doctype": "Affiliate", "user": ensure_user(email), **values}).insert()


class IntegrationTestAffiliate(IntegrationTestCase):
	"""An affiliate's code is set once, and only a System Manager reaches affiliate records."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)

	def test_pending_affiliates_without_a_code_do_not_clash(self):
		first = make_affiliate("affiliate.pending.one@example.test", affiliate_code="")
		second = make_affiliate("affiliate.pending.two@example.test")

		for affiliate in (first, second):
			self.assertIsNone(frappe.db.get_value("Affiliate", affiliate.name, "affiliate_code"))

	def test_code_is_unique(self):
		make_affiliate("affiliate.code.one@example.test", affiliate_code="abcd2345")

		with self.assertRaises(frappe.UniqueValidationError):
			make_affiliate("affiliate.code.two@example.test", affiliate_code="abcd2345")

	def test_code_cannot_change_once_set(self):
		affiliate = make_affiliate("affiliate.code.fixed@example.test")
		affiliate.update({"status": "Active", "affiliate_code": "ABCD2345"})
		affiliate.save()
		self.assertEqual(affiliate.affiliate_code, "abcd2345")

		affiliate.affiliate_code = "wxyz6789"
		with self.assertRaises(frappe.ValidationError):
			affiliate.save()

		affiliate.reload()
		affiliate.affiliate_code = None
		with self.assertRaises(frappe.ValidationError):
			affiliate.save()

	def test_only_a_system_manager_reaches_affiliate_records(self):
		customer = ensure_user("affiliate.customer@example.test")

		for doctype in AFFILIATE_DOCTYPES:
			for permission in ("read", "write", "create"):
				with self.subTest(doctype=doctype, permission=permission):
					self.assertFalse(frappe.has_permission(doctype, permission, user=customer))
					self.assertTrue(frappe.has_permission(doctype, permission, user="Administrator"))


class IntegrationTestAffiliateReview(IntegrationTestCase):
	"""A user asks once, a System Manager decides, and the code survives a pause."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		self.addCleanup(frappe.set_user, "Administrator")
		self.applicant = ensure_user("affiliate.applicant@example.test")

	def test_apply_creates_one_pending_request(self):
		frappe.set_user(self.applicant)

		self.assertIsNone(get_affiliate())
		self.assertEqual(apply()["status"], "Pending")
		self.assertEqual(apply()["status"], "Pending")
		self.assertEqual(frappe.db.count("Affiliate", {"user": self.applicant}), 1)

	def test_a_lost_race_returns_the_request_without_an_error_message(self):
		first = self.request()
		frappe.clear_messages()

		self.assertEqual(Affiliate.create_request(self.applicant).name, first.name)
		self.assertEqual(frappe.message_log, [])

	def test_apply_changes_nothing_for_an_active_affiliate(self):
		affiliate = self.approved()
		frappe.set_user(self.applicant)

		self.assertEqual(
			apply(),
			{"status": "Active", "affiliate_code": affiliate.affiliate_code, "rejection_reason": None},
		)

	def test_a_rejected_user_can_ask_again(self):
		affiliate = self.request()
		affiliate.reject("No audience yet")
		frappe.set_user(self.applicant)
		self.assertEqual(get_affiliate()["rejection_reason"], "No audience yet")

		self.assertEqual(apply()["status"], "Pending")
		affiliate.reload()
		self.assertIsNone(affiliate.reviewed_by)
		self.assertIsNone(affiliate.rejection_reason)

	def test_a_disabled_user_cannot_ask_again(self):
		affiliate = self.approved()
		affiliate.disable()
		frappe.set_user(self.applicant)

		with self.assertRaises(AffiliateStatusError):
			apply()
		self.assertEqual(
			get_affiliate(), {"status": "Disabled", "affiliate_code": None, "rejection_reason": None}
		)

	def test_approval_sets_a_readable_code_once(self):
		affiliate = self.approved()

		self.assertEqual(affiliate.status, "Active")
		self.assertEqual(affiliate.reviewed_by, "Administrator")
		self.assertEqual(len(affiliate.affiliate_code), CODE_LENGTH)
		self.assertTrue(set(affiliate.affiliate_code) <= set(CODE_ALPHABET))

		code = affiliate.affiliate_code
		affiliate.approve()
		self.assertEqual(affiliate.affiliate_code, code)
		self.assertIn("Already approved", frappe.message_log[-1]["message"])

	def test_a_second_rejection_does_nothing(self):
		affiliate = self.request()
		affiliate.reject("First reason")
		affiliate.reject("Second reason")

		self.assertEqual(affiliate.rejection_reason, "First reason")
		self.assertIn("Already rejected", frappe.message_log[-1]["message"])

	def test_actions_need_the_right_status(self):
		affiliate = self.request()
		for action in (affiliate.disable, affiliate.enable):
			with self.subTest(action=action.__name__), self.assertRaises(AffiliateStatusError):
				action()

		with self.assertRaises(frappe.ValidationError):
			affiliate.reject("  ")

		affiliate.approve()
		affiliate.disable()
		with self.assertRaises(AffiliateStatusError):
			affiliate.approve()

	def test_the_other_review_says_who_decided_first(self):
		approved = self.approved()
		approved.reject("Too late")
		self.assertEqual(approved.status, "Active")
		self.assertIn("Already approved", frappe.message_log[-1]["message"])

		rejected = make_affiliate("affiliate.rejected.first@example.test")
		rejected.reject("No audience yet")
		rejected.approve()
		self.assertEqual((rejected.status, rejected.affiliate_code), ("Rejected", None))
		self.assertIn("Already rejected", frappe.message_log[-1]["message"])

	def test_enable_keeps_the_code(self):
		affiliate = self.approved()
		code = affiliate.affiliate_code
		affiliate.disable()
		affiliate.enable()

		self.assertEqual((affiliate.status, affiliate.affiliate_code), ("Active", code))

	def test_only_a_system_manager_reviews(self):
		affiliate = self.request()
		frappe.set_user(ensure_user("affiliate.not.operator@example.test"))

		for action in (affiliate.approve, affiliate.disable, affiliate.enable):
			with self.subTest(action=action.__name__), self.assertRaises(frappe.PermissionError):
				action()
		with self.assertRaises(frappe.PermissionError):
			affiliate.reject("No")

	def test_code_generation_skips_a_taken_code(self):
		make_affiliate("affiliate.taken@example.test", affiliate_code="abcd2345")

		with patch("secrets.choice", side_effect=list("abcd2345wxyz6789")):
			self.assertEqual(generate_affiliate_code(), "wxyz6789")

	def request(self) -> "frappe.Document":
		return make_affiliate(self.applicant)

	def approved(self) -> "frappe.Document":
		affiliate = self.request()
		affiliate.approve()
		return affiliate
