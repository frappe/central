import json

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, now_datetime, today

from central.api.affiliates import get_summary
from central.signups.doctype.affiliate.test_affiliate import make_affiliate
from central.signups.doctype.affiliate_link.affiliate_link import AffiliateLink
from central.tests.test_iam import ensure_user


class IntegrationTestAffiliateSummary(IntegrationTestCase):
	"""An affiliate sees their own visits, signups and paying signups, and never a team name."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.get_doc(
			{"doctype": "Product", "product_key": "summary-raven", "title": "Raven", "signup_app": "raven"}
		).insert()
		self.affiliate = make_affiliate("summary.affiliate@example.test")
		self.affiliate.approve()
		other = make_affiliate("summary.other@example.test")
		other.approve()
		self.other = other.name

	def test_the_funnel_counts_visits_signups_and_paying_signups(self):
		for source, product in (
			("youtube", None),
			("youtube", "summary-raven"),
			("linkedin", None),
			(None, None),
		):
			self.visit(source, product)
		self.visit("youtube", None, affiliate=self.other)
		self.visit("youtube", None, days_ago=40)

		for label, product, source, invoice in (
			("Paying", None, "youtube", {}),
			("Product Paying", "summary-raven", "youtube", {}),
			("Credit Only", None, "linkedin", {"amount_paid": 0}),
			("Cost Report", None, None, {"invoice_type": "Cost Report"}),
		):
			team = self.team(label)
			self.referral(team, product, source)
			self.invoice(team, **invoice)

		summary = self.summary()

		self.assertEqual(
			summary["totals"],
			{"visited": 4, "signed_up": 4, "created_site": 2, "added_billing": 2, "converted": 2},
		)
		by_source = {row["source"]: row for row in summary["by_source"]}
		self.assertEqual(
			by_source["youtube"],
			{
				"source": "youtube",
				"visited": 2,
				"signed_up": 2,
				"created_site": 2,
				"added_billing": 2,
				"converted": 2,
			},
		)
		self.assertEqual(by_source[None]["visited"], 1)
		by_product = {row["product"]: row for row in summary["by_product"]}
		self.assertEqual(
			by_product["summary-raven"],
			{
				"product": "summary-raven",
				"visited": 1,
				"signed_up": 1,
				"created_site": 1,
				"added_billing": 1,
				"converted": 1,
			},
		)
		self.assertEqual(by_product[None]["signed_up"], 3)

	def test_each_step_counts_the_teams_that_reached_it(self):
		with_site = self.team("With Site")
		self.referral(with_site, None, "youtube")
		self.record("Site", team=with_site, product=None, subdomain="with-site")

		with_billing = self.team("With Billing")
		self.referral(with_billing, None, "youtube")
		self.record("Payment Method", team=with_billing, status="Active")

		other_product_site = self.team("Other Product Site")
		self.referral(other_product_site, "summary-raven", "youtube")
		self.record("Site", team=other_product_site, product=None, subdomain="other-product")

		self.referral(self.team("Nothing Yet"), None, "youtube")

		self.assertEqual(
			self.summary()["totals"],
			{"visited": 0, "signed_up": 4, "created_site": 2, "added_billing": 1, "converted": 0},
		)

	def test_daily_counts_cover_every_day(self):
		self.visit("youtube", None)
		self.visit("youtube", None, days_ago=3)
		self.referral(self.team("Today"), None, "youtube")

		daily = {row["day"]: row for row in self.summary()["daily"]}

		self.assertEqual(len(daily), 8)
		self.assertEqual(daily[today()], {"day": today(), "clicks": 1, "signups": 1, "paying": 0})
		self.assertEqual(daily[str(add_days(today(), -3))]["clicks"], 1)
		self.assertEqual(
			daily[str(add_days(today(), -1))],
			{"day": str(add_days(today(), -1)), "clicks": 0, "signups": 0, "paying": 0},
		)

	def test_the_previous_period_has_the_same_length(self):
		self.visit("youtube", None)
		self.visit("youtube", None, days_ago=10)
		self.visit("youtube", None, days_ago=20)

		summary = self.summary()

		self.assertEqual(summary["totals"]["visited"], 1)
		self.assertEqual(summary["previous_totals"]["visited"], 1)

	def test_links_and_countries_come_from_the_visit(self):
		AffiliateLink.create_for(self.affiliate.name, "summary-link", utm_campaign="launch")
		visit = self.visit("youtube", None, link="summary-link", country="India")
		self.visit("youtube", None, country="Germany")
		self.referral(self.team("Linked"), None, "youtube", visit=visit)

		summary = self.summary()

		by_link = {row["link"]: row for row in summary["by_link"]}
		self.assertEqual((by_link["summary-link"]["visited"], by_link["summary-link"]["signed_up"]), (1, 1))
		self.assertEqual(by_link[None]["visited"], 1)
		by_country = {row["country"]: row for row in summary["by_country"]}
		self.assertEqual((by_country["India"]["visited"], by_country["India"]["signed_up"]), (1, 1))
		self.assertEqual(by_country["Germany"]["signed_up"], 0)

	def test_a_plain_link_click_counts_for_the_product_the_person_chose(self):
		plain = self.visit("youtube", None)
		self.visit("youtube", None)
		self.referral(self.team("Chose Raven"), "summary-raven", "youtube", visit=plain)

		by_product = {row["product"]: row for row in self.summary()["by_product"]}

		self.assertEqual(
			(by_product["summary-raven"]["visited"], by_product["summary-raven"]["signed_up"]), (1, 1)
		)
		self.assertEqual((by_product[None]["visited"], by_product[None]["signed_up"]), (1, 0))

	def test_a_product_referral_takes_the_conversion_from_a_frappe_cloud_referral(self):
		team = self.team("Both")
		self.referral(team, None, "youtube")
		self.referral(team, "summary-raven", "youtube", affiliate=self.other)
		self.invoice(team)

		self.assertEqual(self.summary()["totals"]["converted"], 0)

		frappe.set_user(frappe.db.get_value("Affiliate", self.other, "user"))
		self.assertEqual(get_summary(add_days(today(), -7), today())["totals"]["converted"], 1)

	def test_a_payment_before_the_referral_does_not_convert(self):
		team = self.team("Already Paying")
		self.invoice(team, days_ago=30)
		self.referral(team, "summary-raven", "youtube")

		self.assertEqual(self.summary()["totals"]["converted"], 0)

		self.invoice(team)
		self.assertEqual(self.summary()["totals"]["converted"], 1)

	def test_the_summary_names_no_team(self):
		team = self.team("Secret Customer")
		self.referral(team, "summary-raven", "youtube")
		self.invoice(team)

		summary = self.summary()

		self.assertEqual(summary["totals"]["converted"], 1)
		self.assertNotIn(team, json.dumps(summary, default=str))
		self.assertNotIn("Secret Customer", json.dumps(summary, default=str))

	def test_only_an_active_affiliate_has_a_summary(self):
		frappe.set_user(ensure_user("summary.stranger@example.test"))
		with self.assertRaises(frappe.PermissionError):
			get_summary(today(), today())

		frappe.set_user("Administrator")
		self.affiliate.disable()
		with self.assertRaises(frappe.PermissionError):
			self.summary()

	def test_the_start_must_not_be_after_the_end(self):
		frappe.set_user(self.affiliate.user)

		with self.assertRaises(frappe.ValidationError):
			get_summary(today(), add_days(today(), -1))

	def test_a_period_is_at_most_a_year(self):
		frappe.set_user(self.affiliate.user)

		get_summary(add_days(today(), -365), today())
		with self.assertRaises(frappe.ValidationError):
			get_summary(add_days(today(), -366), today())

	def summary(self) -> dict:
		frappe.set_user(self.affiliate.user)
		return get_summary(add_days(today(), -7), today())

	def visit(
		self,
		source: str | None,
		product: str | None,
		affiliate: str | None = None,
		days_ago: int = 0,
		**values,
	) -> str:
		visit = frappe.get_doc(
			{
				"doctype": "Affiliate Visit",
				"affiliate": affiliate or self.affiliate.name,
				"product": product,
				"utm_source": source,
				"last_clicked_on": now_datetime(),
				**values,
			}
		).insert()
		if days_ago:
			visit.db_set("creation", add_days(now_datetime(), -days_ago), update_modified=False)

		return visit.name

	def team(self, label: str) -> str:
		owner = ensure_user(f"summary.{label.lower().replace(' ', '.')}@example.test")
		team = frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": label,
				"owner_user": owner,
				"members": [{"user": owner, "role": "Owner", "status": "Active"}],
			}
		).insert()
		return team.name

	def referral(
		self,
		team: str,
		product: str | None,
		source: str | None,
		affiliate: str | None = None,
		visit: str | None = None,
		utm_campaign: str | None = None,
	) -> None:
		frappe.get_doc(
			{
				"doctype": "Product Referral",
				"referred_team": team,
				"product": product,
				"affiliate": affiliate or self.affiliate.name,
				"utm_source": source,
				"utm_campaign": utm_campaign,
				"visit": visit,
			}
		).insert()

	def record(self, doctype: str, **values) -> None:
		doc = frappe.get_doc({"doctype": doctype, **values})
		doc.name = f"summary-{frappe.generate_hash(length=8)}"
		# Only the row matters here, not the billing or machine that would create it.
		doc.db_insert()

	def invoice(
		self, team: str, amount_paid: float = 10, invoice_type: str = "Billable", days_ago: int = 0
	) -> None:
		invoice = frappe.get_doc(
			{
				"doctype": "Invoice",
				"team": team,
				"status": "Paid",
				"invoice_type": invoice_type,
				"amount_paid": amount_paid,
				"paid_at": add_days(now_datetime(), -days_ago),
			}
		)
		invoice.name = f"summary-{frappe.generate_hash(length=8)}"
		# Only the paid row matters here, not the billing that would create it.
		invoice.db_insert()
