import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, now_datetime

from central.identity import signup_email, signup_watch
from central.identity.signup_email import reserve_gmail_account, validate_signup_email
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

	def add_gmail_user(self, email: str) -> None:
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": "Gm", "send_welcome_email": 0}
		).insert()

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

	def test_a_trusted_domain_on_the_temporary_list_is_accepted(self):
		self.addCleanup(signup_email.clear_signup_domains)
		self.block("0-mail.com", status="Trusted")

		validate_signup_email("someone@0-mail.com")

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
			reserve_gmail_account(f"{local[:2]}.{local[2:]}@googlemail.com")
		reserve_gmail_account(f"new.{local}@gmail.com")

	def test_a_code_request_does_not_reveal_a_known_gmail_account(self):
		local = f"gm{frappe.generate_hash(length=8)}"
		self.add_gmail_user(f"{local}@gmail.com")

		validate_signup_email(f"{local[:2]}.{local[2:]}@gmail.com")

	def test_a_flood_from_one_organisation_blocks_it_and_tells_the_operators(self):
		domain = unique_domain()
		with patch(ENQUEUE) as enqueue:
			for department in ("cs", "ee", "me"):
				watch_signup_domain(f"student@{department}.{domain}")
			with self.assertRaises(frappe.TooManyRequestsError):
				watch_signup_domain(f"student@bio.{domain}")

		self.assertEqual(enqueue.call_args.kwargs["domain"], domain)
		with (
			patch("central.identity.signup_watch.get_system_managers", return_value=["ops@example.test"]),
			patch("central.identity.signup_watch.frappe.sendmail") as sendmail,
		):
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
		self.assertEqual(get_organisation_domain("mail.gmail.com"), "gmail.com")

	def test_unrelated_organisations_under_one_public_suffix_count_apart(self):
		self.assertEqual(get_organisation_domain("school.k12.ca.us"), "school.k12.ca.us")
		self.assertEqual(get_organisation_domain("team.github.io"), "team.github.io")

	def test_a_stranger_naming_an_organisations_addresses_cannot_block_it(self):
		from central.users import send_sign_in_code

		domain = unique_domain()
		with patch("central.identity.email_code.frappe.sendmail"), patch(ENQUEUE) as enqueue:
			for index in range(10):
				with patch.object(frappe.local, "request_ip", self.unique_ip()):
					send_sign_in_code(f"victim{index}@{domain}", "Victim")

		enqueue.assert_not_called()
		validate_signup_email(f"real@{domain}")

	def test_a_gmail_subdomain_never_counts_toward_or_blocks_gmail(self):
		with patch(ENQUEUE) as enqueue:
			for index in range(10):
				watch_signup_domain(f"user{index}@mail.gmail.com")
		enqueue.assert_not_called()

		with patch("central.identity.signup_watch.frappe.sendmail") as sendmail:
			save_automatic_block("gmail.com", "Burst")
		self.assertFalse(frappe.db.exists("Signup Domain", "gmail.com"))
		sendmail.assert_not_called()

	def test_an_existing_plus_alias_account_keeps_its_inbox(self):
		local = f"john.doe{frappe.generate_hash(length=6)}"
		self.add_gmail_user(f"{local}+work@gmail.com")

		with self.assertRaisesRegex(frappe.ValidationError, "Aliases"):
			reserve_gmail_account(f"{local}@gmail.com")

	def test_two_spellings_of_one_gmail_inbox_cannot_both_be_created(self):
		local = f"race{frappe.generate_hash(length=6)}"
		reserve_gmail_account(f"{local[:2]}.{local[2:]}@gmail.com")

		with self.assertRaisesRegex(frappe.ValidationError, "Aliases"):
			reserve_gmail_account(f"{local}@googlemail.com")

	def test_a_rolled_back_signup_gives_its_gmail_inbox_up(self):
		local = f"undo{frappe.generate_hash(length=6)}"
		reserve_gmail_account(f"{local}@gmail.com")
		frappe.db.rollback()

		reserve_gmail_account(f"{local}@gmail.com")

	def test_a_deleted_gmail_user_can_sign_up_again(self):
		email = f"gone{frappe.generate_hash(length=6)}@gmail.com"
		self.add_gmail_user(email)

		frappe.delete_doc("User", email, force=True)
		frappe.db.after_commit.run()

		reserve_gmail_account(email)

	def test_a_domain_change_clears_the_cache_again_after_commit(self):
		domain = unique_domain()
		self.block(domain)
		frappe.cache.set_value(signup_email.SIGNUP_DOMAINS_KEY, {})

		frappe.db.after_commit.run()

		self.assertTrue(signup_email.is_blocked_domain(domain))

	def test_a_stale_copy_of_the_domains_expires(self):
		frappe.cache.delete_value(signup_email.SIGNUP_DOMAINS_KEY)
		signup_email.get_signup_domains()

		expiry = frappe.cache.ttl(frappe.cache.make_key(signup_email.SIGNUP_DOMAINS_KEY))
		self.assertTrue(0 < expiry <= signup_email.SIGNUP_DOMAINS_SECONDS)

	def test_only_a_system_manager_can_see_or_change_signup_domains(self):
		from central.tests.test_team_management import create_user

		domain = unique_domain()
		self.block(domain)
		frappe.set_user(create_user(f"member.{frappe.generate_hash(length=6)}@example.test"))
		self.addCleanup(frappe.set_user, "Administrator")

		self.assertFalse(frappe.has_permission("Signup Domain", "read"))
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("Signup Domain", domain).check_permission("read")
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc({"doctype": "Signup Domain", "domain": unique_domain(), "reason": "x"}).insert()


class TestTemporaryDomainRefresh(IntegrationTestCase):
	def setUp(self):
		self.enterContext(self.change_settings("Central Settings", refuse_temporary_emails=1))
		self.addCleanup(frappe.cache.delete_value, signup_email.TEMPORARY_DOMAINS_KEY)
		folder = self.enterContext(tempfile.TemporaryDirectory())
		path = str(Path(folder) / "temporary_email_domains.txt")
		self.enterContext(
			patch("central.identity.signup_email.get_temporary_domains_path", return_value=path)
		)
		self.enterContext(
			patch("central.identity.signup_watch.get_temporary_domains_path", return_value=path)
		)
		frappe.cache.delete_value(signup_email.TEMPORARY_DOMAINS_KEY)

	def refresh(self, domains: list[str]) -> None:
		response = Mock(text="\n".join(domains))
		with patch("central.identity.signup_watch.requests.get", return_value=response):
			signup_watch.refresh_temporary_domains()

	def test_a_fresh_list_replaces_the_shipped_one(self):
		self.refresh([f"temp{index}.example" for index in range(1200)])

		self.assertTrue(signup_email.is_temporary_domain("temp7.example"))
		self.assertFalse(signup_email.is_temporary_domain("mailinator.com"))

	def test_a_signup_waiting_on_the_lock_keeps_the_refreshed_list(self):
		self.refresh([f"temp{index}.example" for index in range(1200)])

		with patch("central.identity.signup_email.BUNDLED_TEMPORARY_DOMAINS", "/nonexistent"):
			signup_email.load_temporary_domains(replace=False)

		self.assertTrue(signup_email.is_temporary_domain("temp7.example"))

	def test_a_list_that_looks_wrong_is_not_saved(self):
		self.refresh([f"temp{index}.example" for index in range(1200)] + ["gmail.com"])
		self.refresh(["only.example"])

		self.assertTrue(signup_email.is_temporary_domain("mailinator.com"))
		self.assertFalse(signup_email.is_temporary_domain("temp7.example"))
