from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase, set_user

from central.api.identity import my_teams
from central.api.teams import (
	accept_invitation,
	create_team,
	invite_team_member,
	set_onboarding_step,
	skip_onboarding,
)
from central.site_provisioning import create_trial_team


def create_user(label: str) -> str:
	email = f"onboarding.{label}.{frappe.generate_hash(length=8)}@example.test"
	frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": label.title(),
			"enabled": 1,
			"send_welcome_email": 0,
		}
	).insert()
	return email


def onboarding_steps(team: str) -> dict[str, str]:
	return {row.step: row.status for row in frappe.get_doc("Team", team).onboarding_steps}


class TestTeamCreation(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = create_user("owner")
		frappe.set_user(self.owner)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_first_team_gets_billing_from_the_request_country(self):
		with patch("central.geo.get_country_from_ip", return_value="India"):
			team = create_team("First Team")["name"]

		self.assertEqual(frappe.db.get_value("Billing Profile", team, "country"), "India")
		self.assertEqual(frappe.db.get_value("Billing Profile", team, "currency"), "INR")
		self.assertTrue(
			frappe.db.exists(
				"Credit Ledger Entry", {"team": team, "reference_type": "Promotion", "currency": "INR"}
			)
		)

	def test_first_team_falls_back_to_india_when_the_country_is_unknown(self):
		with patch("central.geo.get_country_from_ip", return_value=None):
			team = create_team("First Team")["name"]

		self.assertEqual(frappe.db.get_value("Billing Profile", team, "country"), "India")
		self.assertEqual(frappe.db.get_value("Billing Profile", team, "currency"), "INR")

	def test_later_team_gets_no_billing_until_its_profile_is_completed(self):
		create_team("First Team")
		later = create_team("Second Team")["name"]

		self.assertFalse(frappe.db.exists("Billing Profile", later))

	def test_new_team_starts_with_every_onboarding_step_pending(self):
		team = create_team("First Team")["name"]

		self.assertEqual(
			onboarding_steps(team), {"invite": "Pending", "billing": "Pending", "start": "Pending"}
		)

	@IntegrationTestCase.change_settings("Billing Settings", provision_teams_as_trial=0)
	def test_caller_cannot_choose_a_staging_trial(self):
		team = frappe.get_doc({"doctype": "Team", "team_name": "Free Trial", "is_staging_trial": 1}).insert()

		self.assertFalse(team.is_staging_trial)

	@IntegrationTestCase.change_settings("Billing Settings", provision_teams_as_trial=0)
	def test_team_editor_cannot_turn_on_a_staging_trial(self):
		team = frappe.get_doc("Team", create_team("First Team")["name"])
		team.is_staging_trial = 1
		team.save()

		self.assertFalse(frappe.db.get_value("Team", team.name, "is_staging_trial"))

	@IntegrationTestCase.change_settings("Billing Settings", provision_teams_as_trial=1)
	def test_staging_trial_team_has_no_billing_step(self):
		team = create_team("Trial Team")["name"]

		self.assertTrue(frappe.db.get_value("Team", team, "is_staging_trial"))
		self.assertEqual(onboarding_steps(team), {"invite": "Pending", "start": "Pending"})

	def test_trial_funnel_creates_a_team_only_for_a_user_with_none(self):
		team = create_trial_team(self.owner)

		self.assertEqual(frappe.db.get_value("Team", team, "owner_user"), self.owner)
		self.assertIsNone(create_trial_team(self.owner))
		self.assertEqual(frappe.db.count("Team", {"owner_user": self.owner}), 1)

	@patch("frappe.sendmail")
	def test_invited_member_reuses_the_team_without_another_welcome_grant(self, _sendmail):
		team = create_team("Inviting Team")["name"]
		with set_user("Administrator"):
			member = create_user("invitee")
		invitation = invite_team_member(team, member, "Admin")
		credits_before = frappe.get_all("Credit Ledger Entry", filters={"team": team}, pluck="name")

		with set_user(member):
			self.assertEqual(accept_invitation(invitation)["team"], team)
			self.assertIsNone(create_trial_team(member))

		self.assertFalse(frappe.db.exists("Team", {"owner_user": member}))
		self.assertCountEqual(
			frappe.get_all("Credit Ledger Entry", filters={"team": team}, pluck="name"), credits_before
		)

	@patch("frappe.sendmail")
	def test_invited_member_can_get_welcome_credits_for_their_own_first_team(self, _sendmail):
		team = create_team("Inviting Team")["name"]
		with set_user("Administrator"):
			member = create_user("invitee")
		invitation = invite_team_member(team, member, "Admin")

		with set_user(member):
			accept_invitation(invitation)
			personal_team = create_team("Personal Team")["name"]

		self.assertTrue(
			frappe.db.exists("Credit Ledger Entry", {"team": personal_team, "reference_type": "Promotion"})
		)

	def test_the_trial_team_keeps_how_the_signup_first_arrived(self):
		with set_user("Administrator"):
			frappe.get_doc(
				{"doctype": "Product", "product_key": "raven-touch", "title": "Raven", "signup_app": "raven"}
			).insert()

		team = create_trial_team(
			self.owner,
			{
				"utm_source": " linkedin ",
				"utm_campaign": "x" * 300,
				"referrer": "https://frappe.io/raven",
				"product": "raven-touch",
			},
		)

		values = frappe.db.get_value(
			"Team", team, ["utm_source", "utm_campaign", "referrer", "landing_product"], as_dict=True
		)
		self.assertEqual(values.utm_source, "linkedin")
		self.assertEqual(len(values.utm_campaign), 140)
		self.assertEqual(values.referrer, "https://frappe.io/raven")
		self.assertEqual(values.landing_product, "raven-touch")

	def test_an_unknown_landing_product_does_not_stop_the_team(self):
		team = create_trial_team(self.owner, {"product": "no-such-product"})

		self.assertIsNone(frappe.db.get_value("Team", team, "landing_product"))


class TestOnboardingSteps(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = create_user("owner")
		self.admin = create_user("admin")
		frappe.set_user(self.owner)
		self.team = create_team("Onboarding Team")["name"]

		frappe.set_user("Administrator")
		team = frappe.get_doc("Team", self.team)
		team.append("members", {"user": self.admin, "role": "Admin", "status": "Active"})
		team.save()

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_owner_finishes_one_step_and_skips_the_rest(self):
		frappe.set_user(self.owner)
		set_onboarding_step(self.team, "billing", "Done")
		skip_onboarding(self.team)

		self.assertEqual(
			onboarding_steps(self.team), {"invite": "Skipped", "billing": "Done", "start": "Skipped"}
		)
		row = frappe.get_doc("Team", self.team).onboarding_steps[0]
		self.assertEqual(row.updated_by, self.owner)
		self.assertIsNotNone(row.updated_on)

	def test_only_the_owner_can_answer_onboarding(self):
		frappe.set_user(self.admin)

		with self.assertRaises(frappe.PermissionError):
			set_onboarding_step(self.team, "invite", "Skipped")
		with self.assertRaises(frappe.PermissionError):
			skip_onboarding(self.team)
		self.assertEqual(set(onboarding_steps(self.team).values()), {"Pending"})

	def test_a_team_editor_cannot_change_onboarding_through_a_plain_save(self):
		frappe.set_user(self.admin)
		team = frappe.get_doc("Team", self.team)
		team.onboarding_steps[0].status = "Done"

		with self.assertRaises(frappe.PermissionError):
			team.save()

	def test_unknown_step_or_status_is_refused(self):
		frappe.set_user(self.owner)

		with self.assertRaises(frappe.ValidationError):
			set_onboarding_step(self.team, "invite", "Pending")
		with self.assertRaises(frappe.ValidationError):
			set_onboarding_step(self.team, "team", "Done")

	def test_my_teams_lists_pending_steps_for_the_owner_only(self):
		frappe.set_user(self.owner)
		set_onboarding_step(self.team, "invite", "Done")
		owned = next(team for team in my_teams() if team["name"] == self.team)

		frappe.set_user(self.admin)
		joined = next(team for team in my_teams() if team["name"] == self.team)

		self.assertEqual(owned["onboarding"], ["billing", "start"])
		self.assertEqual(joined["onboarding"], [])
