from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from central.billing.revenue import credits
from central.billing.states import transition
from central.billing.tests.test_stripe_adapter import make_stripe_gateway
from central.billing.tests.utils import billing_settings, complete_billing_profile, ensure_team, make_user
from central.signups.credit import get_purchase_state, grant_credit

OWNER = "welcome-credit-owner@example.com"
TEAM = "team-welcome-credit"
SECOND_TEAM = "team-welcome-credit-second"
AMOUNTS = [{"currency": "USD", "amount": 10}]


class TestWelcomeCredit(IntegrationTestCase):
	def setUp(self):
		owner = make_user(OWNER)
		for team in (TEAM, SECOND_TEAM):
			ensure_team(team, owner=owner)
			complete_billing_profile(team, currency="USD")
		self.gateway = make_stripe_gateway().name
		for doctype in ("Credit Ledger Entry", "Credit Wallet", "Payment Method", "Site"):
			frappe.db.delete(doctype, {"team": ["in", [TEAM, SECOND_TEAM]]})

	def activate_payment_method(self, team: str):
		method = frappe.get_doc(
			{
				"doctype": "Payment Method",
				"team": team,
				"gateway": self.gateway,
				"method_type": "Card",
				"status": "Pending Validation",
			}
		).insert(ignore_permissions=True)
		transition(method, "Active")
		method.save(ignore_permissions=True)
		return method

	def add_trial(self, team: str, state: str):
		"""A trial site record. Its conversion is not under test, so it is patched out."""
		self.enterContext(patch("central.signups.credit.convert_team"))
		name = f"trial-{frappe.generate_hash(length=6)}.example.test"
		frappe.get_doc(
			{
				"doctype": "Site",
				"name": name,
				"site_name": name,
				"team": team,
				"server": "server-trial",
				"trial_state": state,
				"trial_ends_on": add_days(nowdate(), 3),
			}
		).db_insert()

	def promotion_count(self, team: str) -> int:
		return frappe.db.count("Credit Ledger Entry", {"team": team, "reference_type": "Promotion"})

	def test_an_active_payment_method_grants_the_welcome_credit_once(self):
		with billing_settings(grant_welcome_credits=1, welcome_credit_amounts=AMOUNTS):
			self.assertEqual(credits.get_balance(TEAM)["balance"], 0)
			self.activate_payment_method(TEAM)
			self.activate_payment_method(TEAM)

		self.assertEqual(credits.get_balance(TEAM)["balance"], 10)
		self.assertEqual(self.promotion_count(TEAM), 1)

	def test_an_owner_gets_the_welcome_credit_on_one_team_only(self):
		with billing_settings(grant_welcome_credits=1, welcome_credit_amounts=AMOUNTS):
			self.activate_payment_method(TEAM)
			self.activate_payment_method(SECOND_TEAM)

		self.assertEqual(self.promotion_count(SECOND_TEAM), 0)

	def test_no_grant_when_grants_are_off_or_the_currency_has_no_amount(self):
		with billing_settings(grant_welcome_credits=0, welcome_credit_amounts=AMOUNTS):
			self.activate_payment_method(TEAM)
		with billing_settings(
			grant_welcome_credits=1, welcome_credit_amounts=[{"currency": "INR", "amount": 1000}]
		):
			self.activate_payment_method(SECOND_TEAM)

		self.assertEqual(self.promotion_count(TEAM), 0)
		self.assertEqual(self.promotion_count(SECOND_TEAM), 0)

	def test_an_operator_credit_replaces_the_welcome_credit(self):
		grant_credit(TEAM, 100, 30, "Beta credit")
		with billing_settings(grant_welcome_credits=1, welcome_credit_amounts=AMOUNTS):
			self.activate_payment_method(TEAM)

		self.assertEqual(credits.get_balance(TEAM)["balance"], 100)

	def test_only_an_operator_grants_credit(self):
		with self.set_user(OWNER), self.assertRaises(frappe.PermissionError):
			grant_credit(TEAM, 100, 30, "Beta credit")

	def test_the_console_asks_for_a_payment_method_and_offers_the_credit(self):
		with billing_settings(grant_welcome_credits=1, welcome_credit_amounts=AMOUNTS):
			state = get_purchase_state(TEAM)

		self.assertTrue(state["payment_method_required"])
		self.assertEqual(state["welcome_credit"]["amount"], 10)

		with billing_settings(grant_welcome_credits=1, welcome_credit_amounts=AMOUNTS):
			self.activate_payment_method(TEAM)
			state = get_purchase_state(TEAM)

		self.assertFalse(state["payment_method_required"])
		self.assertIsNone(state["welcome_credit"])

	@IntegrationTestCase.change_settings("Central Settings", require_payment_method=0)
	def test_no_payment_method_is_asked_for_when_the_requirement_is_off(self):
		self.assertFalse(get_purchase_state(TEAM)["payment_method_required"])

	def test_the_console_names_only_the_teams_own_open_trial(self):
		self.assertIsNone(get_purchase_state(TEAM)["open_trial"])

		self.add_trial(SECOND_TEAM, "Active")
		self.assertIsNone(get_purchase_state(TEAM)["open_trial"])

		self.add_trial(TEAM, "Ended")
		trial = get_purchase_state(TEAM)["open_trial"]
		self.assertEqual((trial["state"], trial["server"]), ("Ended", "server-trial"))

		with patch("central.signups.eligibility.can", return_value=False):
			self.assertIsNone(get_purchase_state(TEAM)["open_trial"]["server"])

	def test_a_team_that_had_a_free_trial_gets_no_welcome_credit(self):
		for state in ("Active", "Ended"):
			with self.subTest(state=state):
				frappe.db.delete("Site", {"team": TEAM})
				self.add_trial(TEAM, state)
				with billing_settings(grant_welcome_credits=1, welcome_credit_amounts=AMOUNTS):
					self.assertIsNone(get_purchase_state(TEAM)["welcome_credit"])
					self.activate_payment_method(TEAM)

				self.assertEqual(self.promotion_count(TEAM), 0)
