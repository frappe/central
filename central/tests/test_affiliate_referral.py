import json
from unittest.mock import patch
from urllib.parse import quote

import frappe
from frappe.auth import CookieManager
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, now_datetime, set_request

from central.signups.affiliates.cookie import COOKIE_NAME, record_referral
from central.signups.doctype.affiliate.test_affiliate import make_affiliate
from central.site_provisioning import create_trial_site, create_trial_team
from central.tests.test_iam import ensure_user

LOG_ERROR = "central.signups.affiliates.cookie.frappe.log_error"


class IntegrationTestAffiliateReferral(IntegrationTestCase):
	"""A signup is credited to the affiliate in the browser's cookie for that product, once."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.db.set_single_value("Central Settings", "affiliate_cookie_days", 30)
		self.affiliate = self.active_affiliate("referral.link.owner@example.test")
		frappe.get_doc(
			{"doctype": "Product", "product_key": "referral-raven", "title": "Raven", "signup_app": "raven"}
		).insert()
		self.owner = ensure_user("referral.signup@example.test")
		self.team = frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": "Referred",
				"owner_user": self.owner,
				"members": [{"user": self.owner, "role": "Owner", "status": "Active"}],
			}
		).insert()

	def test_a_signup_is_credited_and_leaves_other_products_in_the_cookie(self):
		raven = self.visit(product="referral-raven", utm_source="youtube")
		self.browse({"referral-raven": raven, "fc": self.visit()})

		record_referral(self.team.name, "referral-raven")

		referral = frappe.get_doc("Product Referral", f"{self.team.name}::referral-raven")
		self.assertEqual(
			(referral.affiliate, referral.visit, referral.utm_source), (self.affiliate, raven, "youtube")
		)
		self.assertEqual(list(self.cookie()), ["fc"])

	def test_only_the_entry_for_this_product_counts(self):
		self.browse({"referral-raven": self.visit(product="referral-raven")})

		record_referral(self.team.name, None)

		self.assertEqual(self.referral_count(), 0)

	def test_a_visit_that_no_longer_counts_credits_nobody(self):
		member = self.active_affiliate("referral.member@example.test")
		self.team.append(
			"members",
			{"user": frappe.db.get_value("Affiliate", member, "user"), "role": "Admin", "status": "Active"},
		)
		self.team.save()

		cases = {
			"deleted visit": "no-such-visit",
			"click outside the window": self.visit(last_clicked_on=add_days(now_datetime(), -31)),
			"visit for another product": self.visit(product="referral-raven"),
			"affiliate in the team": self.visit(affiliate=member),
		}
		with patch(LOG_ERROR) as log_error:
			for label, visit in cases.items():
				with self.subTest(label):
					self.browse({"fc": visit})
					record_referral(self.team.name, None)
					self.assertEqual(self.referral_count(), 0)

			visit = self.visit()
			frappe.db.set_value("Affiliate", self.affiliate, "status", "Disabled")
			self.browse({"fc": visit})
			record_referral(self.team.name, None)
			self.assertEqual(self.referral_count(), 0)

		log_error.assert_not_called()

	def test_the_first_referral_is_final(self):
		first = self.visit()
		self.browse({"fc": first})
		record_referral(self.team.name, None)

		later = self.visit(affiliate=self.active_affiliate("referral.later@example.test"))
		self.browse({"fc": later})
		record_referral(self.team.name, None)

		self.assertEqual(frappe.db.get_value("Product Referral", f"{self.team.name}::fc", "visit"), first)
		self.assertNotIn(COOKIE_NAME, frappe.local.cookie_manager.cookies)

	def test_a_lost_race_is_not_an_error(self):
		self.browse({"fc": self.visit()})
		record_referral(self.team.name, None)

		self.browse({"fc": self.visit()})
		with (
			patch(
				"central.signups.doctype.product_referral.product_referral.frappe.db.exists",
				return_value=None,
			),
			patch(LOG_ERROR) as log_error,
		):
			record_referral(self.team.name, None)

		self.assertEqual(self.referral_count(), 1)
		log_error.assert_not_called()

	def test_a_failure_is_logged_and_never_stops_the_signup(self):
		self.browse({"fc": self.visit()})

		with (
			patch("central.signups.affiliates.cookie.ProductReferral.record", side_effect=RuntimeError),
			patch(LOG_ERROR) as log_error,
		):
			record_referral(self.team.name, None)

		log_error.assert_called_once()
		self.assertEqual(self.referral_count(), 0)

	def test_a_new_trial_team_is_credited_for_its_signup_product(self):
		self.browse({"referral-raven": self.visit(product="referral-raven")})
		user = ensure_user("referral.newcomer@example.test")

		frappe.set_user(user)
		team = create_trial_team(user, signup_product="referral-raven")

		frappe.set_user("Administrator")
		self.assertTrue(frappe.db.exists("Product Referral", f"{team}::referral-raven"))

	def test_a_plain_link_credits_the_product_the_person_signs_up_for(self):
		plain = self.visit()
		self.browse({"fc": plain})
		user = ensure_user("referral.plain@example.test")

		frappe.set_user(user)
		team = create_trial_team(user, signup_product="referral-raven")

		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Product Referral", f"{team}::referral-raven", "visit"), plain)
		self.assertEqual(frappe.db.get_value("Affiliate Visit", plain, "product"), "referral-raven")
		self.assertNotIn(COOKIE_NAME, frappe.local.cookie_manager.cookies)

	def test_a_disabled_signup_product_counts_as_frappe_cloud(self):
		frappe.db.set_value("Product", "referral-raven", "enabled", 0)
		self.browse({"fc": self.visit()})
		user = ensure_user("referral.disabled@example.test")

		frappe.set_user(user)
		team = create_trial_team(user, signup_product="referral-raven")

		frappe.set_user("Administrator")
		self.assertTrue(frappe.db.exists("Product Referral", f"{team}::fc"))

	def test_another_product_trial_is_credited_only_for_its_first_site(self):
		self.browse({"referral-raven": self.visit(product="referral-raven")})
		self.start_site("referral-raven")
		self.assertTrue(frappe.db.exists("Product Referral", f"{self.team.name}::referral-raven"))

		for earlier in (self.make_site, self.make_queued_trial):
			with self.subTest(earlier.__name__):
				frappe.db.delete("Product Referral")
				frappe.db.delete("Site", {"team": self.team.name})
				frappe.db.delete("Resource Action", {"team": self.team.name})
				earlier("referral-raven")
				self.browse({"referral-raven": self.visit(product="referral-raven")})
				self.start_site("referral-raven")
				self.assertEqual(self.referral_count(), 0)

	def test_a_plain_trial_site_records_nothing(self):
		self.browse({"fc": self.visit()})
		self.start_site(None)

		self.assertEqual(self.referral_count(), 0)

	def active_affiliate(self, email: str) -> str:
		affiliate = make_affiliate(email)
		affiliate.approve()
		return affiliate.name

	def visit(self, affiliate: str | None = None, product: str | None = None, **values) -> str:
		visit = frappe.get_doc(
			{
				"doctype": "Affiliate Visit",
				"affiliate": affiliate or self.affiliate,
				"product": product,
				"last_clicked_on": now_datetime(),
				**values,
			}
		)
		return visit.insert().name

	def browse(self, visits: dict) -> None:
		set_request(
			method="POST",
			path="/api/method/x",
			headers={"Cookie": f"{COOKIE_NAME}={quote(json.dumps(visits))}"},
		)
		frappe.local.cookie_manager = CookieManager()

	def cookie(self) -> dict:
		return json.loads(frappe.local.cookie_manager.cookies[COOKIE_NAME]["value"])

	def referral_count(self) -> int:
		return frappe.db.count("Product Referral", {"referred_team": self.team.name})

	def make_site(self, product: str) -> None:
		site = frappe.get_doc(
			{"doctype": "Site", "team": self.team.name, "product": product, "subdomain": "earlier"}
		)
		site.name = "earlier-referral-site"
		# Only the row matters here, not a running machine.
		site.db_insert()

	def make_queued_trial(self, product: str) -> None:
		action = frappe.get_doc(
			{
				"doctype": "Resource Action",
				"team": self.team.name,
				"resource_type": "Site",
				"action": "create",
				"product": product,
			}
		)
		action.name = "queued-referral-trial"
		# Only the row matters here: a trial asked for and not created yet.
		action.db_insert()

	def start_site(self, product: str | None) -> None:
		with (
			patch("central.site_provisioning.resolve_team", return_value=self.team.name),
			patch("central.site_provisioning.validated_subdomain", return_value="acme"),
			patch("central.site_provisioning.trial_configuration", return_value={}),
			patch("central.site_provisioning.submit_request"),
		):
			create_trial_site(self.team.name, "acme", "key", product)
