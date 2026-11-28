import json
from unittest.mock import patch
from urllib.parse import quote

import frappe
from frappe.auth import CookieManager
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, now_datetime, set_request

from central.api.affiliates import set_affiliate_program
from central.identity.doctype.team.team import Team
from central.signups.affiliate_link import COOKIE_NAME, AffiliateLinkPage
from central.tests.test_iam import ensure_user

PERSON = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0"


class TestAffiliateReferral(IntegrationTestCase):
	"""A click on /r/<code> makes the affiliate the new team's affiliate, unless a rule refuses it."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		self.addCleanup(frappe.set_user, "Administrator")
		for attribute in ("request", "request_ip", "cookie_manager"):
			self.addCleanup(setattr, frappe.local, attribute, getattr(frappe.local, attribute, None))
		frappe.cache.delete_keys("rl:central.signups.affiliate_link")
		self.affiliate = frappe.get_doc(
			{"doctype": "Affiliate", "user": ensure_user("referrer@example.com")}
		).insert()

	def click(self, user_agent: str = PERSON, product: str = "") -> str | None:
		"""Open the affiliate link and return the cookie value it sets, if any."""
		query = "utm_source=linkedin&utm_content=https://www.linkedin.com/posts/123"
		self.set_request(
			f"/r/{self.affiliate.code}",
			{"User-Agent": user_agent},
			f"{query}&product={product}" if product else query,
		)
		response = AffiliateLinkPage(f"r/{self.affiliate.code}").render()
		self.assertEqual(response.status_code, 302)
		cookie = frappe.local.cookie_manager.cookies.get(COOKIE_NAME)
		return cookie and cookie["value"]

	def sign_up(self, email: str, cookie: str | None) -> Team:
		frappe.set_user("Administrator")
		user = ensure_user(email)
		headers = {"Cookie": f"{COOKIE_NAME}={quote(cookie)}"} if cookie else {}
		self.set_request("/api/method/central.api.sites.create_trial_team", headers)
		frappe.set_user(user)
		with patch.object(Team, "provision_billing"):
			return Team.create_for_current_user("Signup")

	def set_request(self, path: str, headers: dict, query_string: str = "") -> None:
		set_request(method="GET", path=path, headers=headers, query_string=query_string)
		frappe.local.request_ip = "203.0.113.7"
		frappe.local.cookie_manager = CookieManager()

	def test_click_becomes_the_teams_affiliate(self):
		team = self.sign_up("customer@example.com", self.click())

		self.assertEqual(team.affiliate, self.affiliate.name)
		self.assertEqual(team.utm_source, "linkedin")
		self.assertEqual(team.utm_content, "https://www.linkedin.com/posts/123")
		self.assertIsNone(team.landing_product)

	def test_expired_cookie_gives_no_affiliate(self):
		visit = json.loads(self.click())
		visit["clicked_on"] = str(add_days(now_datetime(), -31))

		self.assertIsNone(self.sign_up("late@example.com", json.dumps(visit)).affiliate)

	def test_paused_affiliate_gets_no_team(self):
		cookie = self.click()
		self.affiliate.status = "Paused"
		self.affiliate.save()

		self.assertIsNone(self.sign_up("customer@example.com", cookie).affiliate)

	def test_affiliate_cannot_refer_themselves(self):
		self.assertIsNone(self.sign_up("referrer@example.com", self.click()).affiliate)

	def test_bot_click_sets_no_cookie(self):
		self.assertIsNone(self.click("Slackbot-LinkExpanding 1.1 (+https://api.slack.com/robots)"))

	def test_broken_cookie_still_signs_up(self):
		for number, cookie in enumerate(
			(
				"not json",
				"[1, 2]",
				'{"code": 42}',
				json.dumps({"code": self.affiliate.name, "clicked_on": "99999999999999999999"}),
				json.dumps({"code": self.affiliate.name, "clicked_on": str(add_days(now_datetime(), 1))}),
			)
		):
			with self.subTest(cookie=cookie):
				team = self.sign_up(f"broken-{number}@example.com", cookie)
				self.assertIsNone(team.affiliate)


class TestAffiliateProgram(IntegrationTestCase):
	"""A user joins and leaves the affiliate program for themselves."""

	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.db.rollback)
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user("Administrator")
		frappe.set_user(ensure_user("joiner@example.com"))

	def test_disabled_affiliate_is_paused_and_cannot_join_again(self):
		code = set_affiliate_program(True)["affiliate"].code
		frappe.set_user("Administrator")
		affiliate = frappe.get_doc("Affiliate", {"code": code})
		affiliate.enabled = 0
		affiliate.save()
		self.assertEqual(affiliate.status, "Paused")
		frappe.set_user("joiner@example.com")

		with self.assertRaises(frappe.PermissionError):
			set_affiliate_program(True)
