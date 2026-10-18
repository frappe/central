import os
from unittest.mock import Mock, patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, now_datetime

from central.identity import signup_email, signup_watch
from central.identity.signup_email import validate_signup_email
from central.identity.signup_watch import (
	get_organisation_domain,
	save_automatic_block,
	watch_signup_domain,
	watch_signup_ip,
)

ENQUEUE = "central.identity.signup_watch.frappe.enqueue"


def unique_domain(suffix: str = "edu") -> str:
	return f"school{frappe.generate_hash(length=8)}.{suffix}"


class TestSignupGuard(IntegrationTestCase):
	def setUp(self):
		self.enterContext(
			self.change_settings(
				"Central Settings",
				alias_email_domains="frappe.io",
				refuse_temporary_emails=1,
				signup_requests_per_minute=3,
				automatic_block_hours=24,
			)
		)
		self.enterContext(patch.object(frappe.local, "request_ip", self.unique_ip(), create=True))

	def unique_ip(self) -> str:
		return f"ip-{frappe.generate_hash(length=10)}"

	def block(self, domain: str, **values) -> None:
		frappe.get_doc({"doctype": "Signup Domain", "domain": domain, "reason": "Spam", **values}).insert()

	def test_a_blocked_domain_and_its_subdomains_are_refused(self):
		domain = unique_domain()
		self.block(domain)

		for email in (f"a@{domain}", f"a@cs.{domain}"):
			with self.assertRaisesRegex(frappe.ValidationError, "domain is not accepted"):
				validate_signup_email(email)
		validate_signup_email(f"a@not{domain}")

	def test_a_block_ends_on_its_date(self):
		domain = unique_domain()
		self.block(domain, blocked_until=add_to_date(now_datetime(), hours=-1))

		validate_signup_email(f"a@{domain}")

	def test_a_trusted_subdomain_wins_over_its_blocked_parent(self):
		domain = unique_domain()
		self.block(domain)
		self.block(f"cs.{domain}", status="Trusted")

		validate_signup_email(f"a@cs.{domain}")

	def test_the_domain_check_reads_the_cache_not_the_table(self):
		domain = unique_domain()
		self.block(domain)
		signup_email.get_signup_domains()

		with patch("central.identity.signup_email.frappe.get_all", side_effect=AssertionError("table read")):
			self.assertTrue(signup_email.is_blocked_domain(domain))

	def test_saving_a_domain_clears_the_cache(self):
		domain = unique_domain()
		signup_email.get_signup_domains()
		self.block(domain)

		self.assertTrue(signup_email.is_blocked_domain(domain))
		frappe.delete_doc("Signup Domain", domain)
		self.assertFalse(signup_email.is_blocked_domain(domain))

	def test_a_temporary_email_provider_is_refused_while_the_setting_is_on(self):
		with self.assertRaisesRegex(frappe.ValidationError, "domain is not accepted"):
			validate_signup_email("someone@mailinator.com")

		with self.change_settings("Central Settings", refuse_temporary_emails=0):
			validate_signup_email("someone@mailinator.com")

	def test_a_plus_alias_is_refused_except_on_an_allowed_domain(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Aliases"):
			validate_signup_email(f"a{frappe.generate_hash(length=6)}+1@example.org")
		validate_signup_email(f"a{frappe.generate_hash(length=6)}+1@frappe.io")

	def test_a_dotted_spelling_of_a_known_gmail_account_is_refused(self):
		local = f"gm{frappe.generate_hash(length=8)}"
		frappe.get_doc(
			{"doctype": "User", "email": f"{local}@gmail.com", "first_name": "Gm", "send_welcome_email": 0}
		).insert()

		with self.assertRaisesRegex(frappe.ValidationError, "Aliases"):
			validate_signup_email(f"{local[:2]}.{local[2:]}@googlemail.com")
		validate_signup_email(f"new.{local}@gmail.com")

	def test_a_flood_from_one_organisation_blocks_it_and_tells_the_operators(self):
		domain = unique_domain()
		with patch(ENQUEUE) as enqueue:
			for department in ("cs", "ee", "me"):
				watch_signup_domain(f"student@{department}.{domain}")
			with self.assertRaises(frappe.TooManyRequestsError):
				watch_signup_domain(f"student@bio.{domain}")

		self.assertEqual(enqueue.call_args.kwargs["domain"], domain)
		with patch("central.identity.signup_watch.frappe.sendmail") as sendmail:
			save_automatic_block(domain, enqueue.call_args.kwargs["reason"])

		entry = frappe.get_doc("Signup Domain", domain)
		self.assertEqual((entry.status, entry.source), ("Blocked", "Automatic"))
		self.assertGreater(entry.blocked_until, now_datetime())
		sendmail.assert_called_once()
		with self.assertRaisesRegex(frappe.ValidationError, "domain is not accepted"):
			validate_signup_email(f"another@{domain}")

	def test_a_flood_from_one_ip_blocks_that_ip_only(self):
		for _attempt in range(3):
			watch_signup_ip()
		with self.assertRaises(frappe.TooManyRequestsError):
			watch_signup_ip()
		with self.assertRaises(frappe.TooManyRequestsError):
			watch_signup_ip()

		with patch.object(frappe.local, "request_ip", self.unique_ip()):
			watch_signup_ip()

	def test_a_refused_signup_gets_no_code_email(self):
		from central.users import send_sign_in_code

		with patch("central.identity.email_code.frappe.sendmail") as sendmail:
			for email in ("someone@mailinator.com", f"a{frappe.generate_hash(length=6)}+1@example.org"):
				with self.assertRaises(frappe.ValidationError):
					send_sign_in_code(email, "Someone")

		sendmail.assert_not_called()

	def test_a_trusted_domain_and_a_public_provider_are_limited_by_ip_only(self):
		domain = unique_domain()
		self.block(domain, status="Trusted")
		with patch(ENQUEUE) as enqueue:
			for index in range(10):
				watch_signup_domain(f"user{index}@{domain}")
				watch_signup_domain(f"user{index}{frappe.generate_hash(length=6)}@gmail.com")

		enqueue.assert_not_called()

	def test_the_limit_can_be_turned_off(self):
		domain = unique_domain()
		with (
			self.change_settings("Central Settings", signup_requests_per_minute=0),
			patch(ENQUEUE) as enqueue,
		):
			for index in range(10):
				watch_signup_ip()
				watch_signup_domain(f"user{index}@{domain}")

		enqueue.assert_not_called()

	def test_an_automatic_block_leaves_a_trusted_domain_alone(self):
		domain = unique_domain()
		self.block(domain, status="Trusted")

		with patch("central.identity.signup_watch.frappe.sendmail") as sendmail:
			save_automatic_block(domain, "Burst")

		self.assertEqual(frappe.db.get_value("Signup Domain", domain, "status"), "Trusted")
		sendmail.assert_not_called()

	def test_departments_count_toward_their_organisation(self):
		self.assertEqual(get_organisation_domain("cs.uni.edu"), "uni.edu")
		self.assertEqual(get_organisation_domain("cs.uni.ac.in"), "uni.ac.in")
		self.assertEqual(get_organisation_domain("uni.ac.in"), "uni.ac.in")
		self.assertEqual(get_organisation_domain("mail.example.de"), "example.de")


class TestTemporaryDomainRefresh(IntegrationTestCase):
	def setUp(self):
		self.path = signup_email.get_temporary_domains_path()
		self.addCleanup(lambda: os.path.exists(self.path) and os.remove(self.path))

	def refresh(self, domains: list[str]) -> None:
		response = Mock(text="\n".join(domains))
		with patch("central.identity.signup_watch.requests.get", return_value=response):
			signup_watch.refresh_temporary_domains()

	def test_a_fresh_list_replaces_the_shipped_one(self):
		domains = [f"temp{index}.example" for index in range(1200)]
		self.refresh(domains)

		self.assertIn("temp7.example", signup_email.get_temporary_domains())
		self.assertNotIn("mailinator.com", signup_email.get_temporary_domains())

	def test_a_list_that_looks_wrong_is_not_saved(self):
		self.refresh([f"temp{index}.example" for index in range(1200)] + ["gmail.com"])
		self.refresh(["only.example"])

		self.assertIn("mailinator.com", signup_email.get_temporary_domains())
