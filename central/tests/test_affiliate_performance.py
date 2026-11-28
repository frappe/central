import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, now_datetime

from central.api.affiliates import get_affiliate_performance
from central.tests.test_iam import ensure_user


class TestAffiliatePerformance(IntegrationTestCase):
	"""An affiliate sees counts for its own referred teams only, by step, period and group."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		self.addCleanup(frappe.set_user, "Administrator")
		self.user = ensure_user("performer@example.com")
		self.affiliate = self.make_affiliate(self.user)
		other = self.make_affiliate(ensure_user("other-performer@example.com"))

		# A team counts under the product of its trial site.
		frappe.get_doc(
			{"doctype": "Product", "name": "test-crm", "product_key": "test-crm", "title": "Test CRM"}
		).db_insert()
		post = "https://www.youtube.com/watch?v=1"
		paying = self.make_team(
			self.affiliate,
			utm_source="YouTube",
			utm_campaign="demo",
			utm_content=post,
			landing_product="test-crm",
		)
		self.add_row("Site", paying, site_name=f"{paying}.example.com", server="server", product="test-crm")
		self.add_row("Payment Method", paying, status="Active", gateway="Stripe", method_type="Card")
		self.add_row(
			"Invoice",
			paying,
			status="Paid",
			invoice_type="Billable",
			amount_paid=10,
			paid_at=now_datetime(),
		)
		# The console makes the post a link, so a script URL must never reach it.
		card_only = self.make_team(
			self.affiliate, utm_source="YouTube", utm_campaign="demo", utm_content="javascript:alert(1)"
		)
		self.add_row("Payment Method", card_only, status="Active", gateway="Stripe", method_type="Card")
		# A server alone is not a started site.
		server_only = self.make_team(self.affiliate)
		self.add_row("Virtual Machine", server_only)
		self.make_team(self.affiliate, days_ago=200)
		self.make_team(other)

	def make_affiliate(self, user: str) -> str:
		return frappe.get_doc({"doctype": "Affiliate", "user": user}).insert().name

	def make_team(self, affiliate: str, days_ago: int = 1, **values) -> str:
		team = frappe.get_doc(
			{"doctype": "Team", "team_name": "Referred", "owner_user": "Administrator", **values}
		)
		team.affiliate = affiliate
		team.insert()
		team.db_set("creation", add_days(now_datetime(), -days_ago))
		return team.name

	def add_row(self, doctype: str, team: str, **values) -> None:
		values.setdefault("name", frappe.generate_hash(length=10))
		frappe.get_doc({"doctype": doctype, "team": team, **values}).db_insert()

	def performance(self, period: str = "90d", product: str | None = None) -> dict:
		frappe.set_user(self.user)
		return get_affiliate_performance(period, product)

	def test_counts_each_step_for_the_period(self):
		performance = self.performance()

		self.assertEqual(
			performance["totals"],
			{
				"signups": 3,
				"paying": 1,
				"still_paying": 1,
				"still_paying_days": 35,
				"previous_signups": 0,
				"previous_paying": 0,
			},
		)
		self.assertEqual(
			performance["funnel"],
			{"signed_up": 3, "started_site": 2, "added_card": 2, "paying": 1, "waiting_to_pay": 1},
		)
		self.assertEqual(sum(week["signups"] for week in performance["weekly"]), 3)
		self.assertEqual(
			performance["campaigns"][0],
			{
				"campaign": "demo",
				"source": "YouTube",
				"product": "Test CRM",
				"signups": 1,
				"paying": 1,
				"post_url": "https://www.youtube.com/watch?v=1",
			},
		)

	def test_campaigns_link_only_to_web_pages(self):
		post_urls = {row["post_url"] for row in self.performance()["campaigns"]}

		self.assertEqual(post_urls, {"https://www.youtube.com/watch?v=1", None})

	def test_all_time_includes_older_teams_but_never_another_affiliates(self):
		self.assertEqual(self.performance("all")["totals"]["signups"], 4)

	def test_only_an_affiliate_sees_performance(self):
		frappe.set_user(ensure_user("stranger@example.com"))
		with self.assertRaises(frappe.PermissionError):
			get_affiliate_performance()
