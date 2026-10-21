from unittest.mock import patch

import frappe
from frappe.auth import CookieManager
from frappe.tests import IntegrationTestCase
from frappe.utils import set_request

from central.api.affiliates import create_link, get_links
from central.signups.affiliates.link import AffiliateLinkPage
from central.signups.doctype.affiliate.test_affiliate import make_affiliate
from central.signups.doctype.affiliate_visit.affiliate_visit import set_country
from central.tests.test_iam import ensure_user

BROWSER = "Mozilla/5.0 (X11; Linux x86_64) Firefox/140.0"


class IntegrationTestAffiliateNamedLinks(IntegrationTestCase):
	"""An affiliate names links such as /r/bwh. A link fixes its product, source and campaign."""

	def setUp(self):
		super().setUp()
		# A request left by an earlier test would put link creation under its rate limit.
		frappe.local.request = None
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.get_doc(
			{"doctype": "Product", "product_key": "named-crm", "title": "CRM", "signup_app": "crm"}
		).insert()
		self.affiliate = make_affiliate("named.affiliate@example.test")
		self.affiliate.approve()
		other = make_affiliate("named.other@example.test")
		other.approve()
		self.other = other
		self.stranger = ensure_user("named.stranger@example.test")
		# Unique, so a link already in the site's data never clashes with the test's.
		self.slug = f"test-{frappe.generate_hash(length=8)}"
		frappe.set_user(self.affiliate.user)

	def test_a_named_link_keeps_its_product_source_and_campaign(self):
		self.assertEqual(
			create_link(f"  {self.slug.upper()} ", "named-crm", " youtube ", "diwali-2026"),
			{"slug": self.slug},
		)

		self.assertEqual(
			[
				{key: row[key] for key in ("slug", "product", "utm_source", "utm_campaign")}
				for row in get_links()
			],
			[
				{
					"slug": self.slug,
					"product": "named-crm",
					"utm_source": "youtube",
					"utm_campaign": "diwali-2026",
				}
			],
		)

	def test_an_empty_slug_gets_a_random_one(self):
		slug = create_link(utm_campaign="launch")["slug"]

		self.assertEqual(len(slug), 8)
		self.assertTrue(frappe.db.exists("Affiliate Link", slug))

	def test_a_link_needs_a_valid_free_slug_and_a_campaign(self):
		create_link(self.slug, utm_campaign="launch")
		for slug in (self.slug, "ab", f"-{self.slug}", f"{self.slug}_x", self.other.affiliate_code):
			with self.subTest(slug=slug), self.assertRaises(frappe.ValidationError):
				create_link(slug, utm_campaign="launch")

		with self.assertRaises(frappe.ValidationError):
			create_link("new-link", product="no-such-product", utm_campaign="launch")

		with self.assertRaises(frappe.ValidationError):
			create_link("no-campaign", utm_campaign="  ")

	def test_a_slug_taken_in_a_race_says_so(self):
		create_link(self.slug, utm_campaign="launch")
		frappe.clear_messages()

		with (
			patch(
				"central.signups.doctype.affiliate_link.affiliate_link.frappe.db.exists", return_value=None
			),
			self.assertRaisesRegex(frappe.ValidationError, "is taken"),
		):
			create_link(self.slug, utm_campaign="launch")

		self.assertEqual(len(frappe.local.message_log), 1)

	def test_only_an_active_affiliate_has_links(self):
		create_link("mine", utm_campaign="launch")
		frappe.set_user(self.other.user)
		self.assertEqual(get_links(), [])

		frappe.set_user(self.stranger)
		for call in (get_links, create_link):
			with self.subTest(call=call.__name__), self.assertRaises(frappe.PermissionError):
				call()

	def test_a_click_on_a_named_link_records_the_link(self):
		create_link(self.slug, "named-crm", "youtube", "diwali-2026")
		frappe.set_user("Guest")

		with patch("frappe.enqueue") as enqueue:
			response = self.click(self.slug.upper(), query={"product": "ignored", "utm_medium": "video"})

		self.assertEqual(
			response.headers["Location"],
			"/dashboard/signup?product=named-crm&utm_source=youtube&utm_medium=video&utm_campaign=diwali-2026",
		)
		visit = frappe.get_last_doc("Affiliate Visit", {"affiliate": self.affiliate.name})
		self.assertEqual(
			(visit.link, visit.product, visit.utm_campaign), (self.slug, "named-crm", "diwali-2026")
		)
		self.assertEqual(enqueue.call_args.kwargs["ip"], "203.0.113.7")

	def test_the_country_is_kept_and_the_address_is_not(self):
		frappe.set_user("Administrator")
		visit = frappe.get_doc(
			{
				"doctype": "Affiliate Visit",
				"affiliate": self.affiliate.name,
				"last_clicked_on": frappe.utils.now_datetime(),
			}
		).insert()

		with patch(
			"central.signups.doctype.affiliate_visit.affiliate_visit.get_country_from_ip",
			return_value="India",
		):
			set_country(visit.name, "203.0.113.7")

		self.assertEqual(frappe.db.get_value("Affiliate Visit", visit.name, "country"), "India")
		self.assertNotIn("203.0.113.7", str(frappe.get_doc("Affiliate Visit", visit.name).as_dict()))

	def click(self, slug: str, query: dict):
		set_request(method="GET", path=f"/r/{slug}", query_string=query, headers={"User-Agent": BROWSER})
		frappe.local.cookie_manager = CookieManager()
		frappe.local.request_ip = "203.0.113.7"
		return AffiliateLinkPage(f"r/{slug}").render()
