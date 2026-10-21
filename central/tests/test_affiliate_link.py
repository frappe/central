import json
from unittest.mock import patch
from urllib.parse import quote

import frappe
from frappe.auth import CookieManager
from frappe.tests import IntegrationTestCase
from frappe.utils import set_request
from frappe.website.path_resolver import PathResolver

from central.api.affiliates import get_link_products
from central.signups.affiliates.cookie import COOKIE_NAME
from central.signups.affiliates.link import AffiliateLinkPage
from central.signups.doctype.affiliate.test_affiliate import make_affiliate
from central.tests.test_iam import ensure_user

BROWSER = "Mozilla/5.0 (X11; Linux x86_64) Firefox/140.0"


class IntegrationTestAffiliateLink(IntegrationTestCase):
	"""A person's click on /r/<code> leaves one visit per product in the cookie, then goes to signup."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		self.addCleanup(frappe.set_user, "Administrator")
		self.affiliate = make_affiliate("link.affiliate@example.test")
		self.affiliate.approve()
		self.code = self.affiliate.affiliate_code
		self.customer = ensure_user("link.customer@example.test")
		frappe.get_doc(
			{"doctype": "Product", "product_key": "link-raven", "title": "Raven", "signup_app": "raven"}
		).insert()
		frappe.set_user("Guest")

	def test_a_click_records_a_visit_and_forwards_the_query(self):
		response = self.click(
			query={"product": "link-raven", "utm_source": "youtube", "to": "https://evil.test"}
		)

		self.assertEqual(response.status_code, 302)
		self.assertEqual(
			response.headers["Location"], "/dashboard/signup?product=link-raven&utm_source=youtube"
		)
		self.assertEqual(response.headers["Cache-Control"], "no-store")

		visit = frappe.get_doc("Affiliate Visit", self.cookie()["link-raven"])
		self.assertEqual(
			(visit.affiliate, visit.product, visit.utm_source), (self.affiliate.name, "link-raven", "youtube")
		)
		self.assertIsNone(visit.utm_medium)

		cookie = frappe.local.cookie_manager.cookies[COOKIE_NAME]
		self.assertTrue(cookie["httponly"])
		self.assertEqual(cookie["max_age"], 30 * 24 * 60 * 60)

	def test_hooks_route_the_link_to_this_page(self):
		set_request(method="GET", path=f"/r/{self.code}")

		self.assertIsInstance(PathResolver(f"r/{self.code}").resolve()[1], AffiliateLinkPage)

	def test_the_code_matches_in_any_case(self):
		self.click(code=self.code.upper())

		self.assertIn("fc", self.cookie())

	def test_an_unknown_or_disabled_product_counts_as_frappe_cloud(self):
		frappe.db.set_value("Product", "link-raven", "enabled", 0)
		response = self.click(query={"product": "link-raven"})

		self.assertEqual(response.headers["Location"], "/dashboard/signup")
		self.assertEqual(list(self.cookie()), ["fc"])

	def test_the_product_key_is_stored_as_saved(self):
		response = self.click(query={"product": "LINK-Raven"})

		self.assertEqual(response.headers["Location"], "/dashboard/signup?product=link-raven")
		self.assertEqual(list(self.cookie()), ["link-raven"])

	def test_the_same_click_again_reuses_the_visit(self):
		self.click(query={"utm_source": "youtube"})
		first = self.cookie()

		self.click(query={"utm_source": "youtube"}, cookie=first)
		self.assertEqual(self.cookie(), first)

		self.click(query={"utm_source": "linkedin"}, cookie=first)
		self.assertNotEqual(self.cookie()["fc"], first["fc"])
		self.assertEqual(frappe.db.count("Affiliate Visit", {"affiliate": self.affiliate.name}), 2)

	def test_each_product_keeps_its_own_visit(self):
		self.click()
		frappe_cloud = self.cookie()
		self.click(query={"product": "link-raven"}, cookie=frappe_cloud)

		self.assertEqual(set(self.cookie()), {"fc", "link-raven"})
		self.assertEqual(self.cookie()["fc"], frappe_cloud["fc"])

	def test_a_deleted_visit_or_bad_cookie_starts_a_new_visit(self):
		for cookie in ({"fc": "missing-visit"}, "not json", ["fc"]):
			with self.subTest(cookie=cookie):
				self.click(cookie=cookie)
				self.assertTrue(frappe.db.exists("Affiliate Visit", self.cookie()["fc"]))

	def test_clicks_that_do_not_count_still_reach_signup(self):
		cases = {
			"unknown code": {"code": "zzzz9999"},
			"head request": {"method": "HEAD"},
			"crawler": {"user_agent": "Mozilla/5.0 (compatible; Googlebot/2.1)"},
			"link preview": {"user_agent": "facebookexternalhit/1.1"},
			"whatsapp preview": {"user_agent": "WhatsApp/2.24.1 A"},
			"telegram preview": {"user_agent": "TelegramBot (like TwitterBot)"},
			"slack preview": {"user_agent": "Slackbot 1.0 (+https://api.slack.com/robots)"},
			"no user agent": {"user_agent": ""},
		}
		for label, request in cases.items():
			with self.subTest(label):
				self.assertEqual(self.click(**request).status_code, 302)
				self.assertNotIn(COOKIE_NAME, frappe.local.cookie_manager.cookies)

		self.affiliate.db_set("status", "Disabled")
		self.click()
		self.assertEqual(frappe.db.count("Affiliate Visit", {"affiliate": self.affiliate.name}), 0)

	def test_people_whose_browser_names_look_like_bots_count(self):
		for user_agent in (
			"Mozilla/5.0 (Linux; Android 14) Chrome/140.0 Mobile Telegram-Android/11.0",
			"Mozilla/5.0 (Linux; Android 12; CUBOT KINGKONG 7) Chrome/140.0 Mobile Safari/537.36",
		):
			with self.subTest(user_agent=user_agent):
				self.click(user_agent=user_agent)
				self.assertIn("fc", self.cookie())

	def test_nothing_is_recorded_when_the_cookie_cannot_last(self):
		frappe.db.set_single_value("Central Settings", "affiliate_cookie_days", 0)
		self.click()

		self.assertNotIn(COOKIE_NAME, frappe.local.cookie_manager.cookies)
		self.assertEqual(frappe.db.count("Affiliate Visit", {"affiliate": self.affiliate.name}), 0)

	def test_the_affiliate_own_click_does_not_count(self):
		frappe.set_user(self.affiliate.user)
		self.click()
		self.assertNotIn(COOKIE_NAME, frappe.local.cookie_manager.cookies)

		frappe.set_user(self.customer)
		self.click()
		self.assertIn("fc", self.cookie())

	def test_clicks_over_the_rate_limit_do_not_count(self):
		ip = f"198.51.100.{frappe.generate_hash(length=8)}"
		with patch("central.signups.affiliates.link.CLICKS_PER_HOUR", 1):
			self.click(ip=ip, code="zzzz9999")
			self.click(ip=ip, query={"utm_source": "a"})
			response = self.click(ip=ip, query={"utm_source": "b"})

		self.assertEqual(response.status_code, 302)
		self.assertEqual(frappe.db.count("Affiliate Visit", {"affiliate": self.affiliate.name}), 1)

	def test_the_link_builder_lists_enabled_products_only(self):
		frappe.set_user(self.customer)
		self.assertIn("link-raven", [row.name for row in get_link_products()])

		frappe.db.set_value("Product", "link-raven", "enabled", 0)
		self.assertNotIn("link-raven", [row.name for row in get_link_products()])

	def test_only_get_and_head_are_served(self):
		self.assertEqual(self.click(method="POST").status_code, 405)

	def click(self, code=None, query=None, cookie=None, method="GET", user_agent=BROWSER, ip=None):
		path = f"/r/{code or self.code}"
		headers = {"User-Agent": user_agent} if user_agent else {}
		if cookie is not None:
			value = cookie if isinstance(cookie, str) else json.dumps(cookie)
			headers["Cookie"] = f"{COOKIE_NAME}={quote(value)}"

		set_request(method=method, path=path, query_string=query or {}, headers=headers)
		frappe.local.cookie_manager = CookieManager()
		frappe.local.request_ip = ip or f"203.0.113.{frappe.generate_hash(length=8)}"
		return AffiliateLinkPage(path).render()

	def cookie(self) -> dict:
		return json.loads(frappe.local.cookie_manager.cookies[COOKIE_NAME]["value"])
