# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Scenarios: asking what a different configuration would do, without adopting it."""

import frappe
from central.billing import settings
from central.billing.projection import scenario
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	add_segment,
	billing_settings,
	ensure_team,
	make_billing_subscription,
	make_plan,
)

TEAM = "team-scenario"
CLUSTER = "ap-south-1"
PLAN = "bundle-scenario"
TODAY = "2026-08-06"


class TestTheOverrideContext(IntegrationTestCase):
	"""Overrides change what is read, never what is stored."""

	def test_without_an_override_the_document_is_read(self):
		with billing_settings(dunning_retry_days="1, 3, 7", suspend_after_days=14):
			self.assertEqual(settings.dunning_retry_days(), [1, 3, 7])
			self.assertEqual(settings.suspend_after_days(), 14)

	def test_an_override_is_read_instead(self):
		with billing_settings(dunning_retry_days="1, 3, 7", suspend_after_days=14):
			with settings.overridden(dunning_retry_days="2, 5, 10", suspend_after_days=21):
				self.assertEqual(settings.dunning_retry_days(), [2, 5, 10])
				self.assertEqual(settings.suspend_after_days(), 21)

	def test_the_document_is_untouched_by_an_override(self):
		# The point of the whole seam: asking costs nobody their configuration.
		with billing_settings(suspend_after_days=14):
			with settings.overridden(suspend_after_days=21):
				pass
			self.assertEqual(settings.suspend_after_days(), 14)
			self.assertEqual(
				frappe.db.get_single_value("Billing Settings", "suspend_after_days"), 14
			)

	def test_the_override_lifts_when_the_block_ends(self):
		with billing_settings(suspend_after_days=14):
			with settings.overridden(suspend_after_days=21):
				self.assertEqual(settings.suspend_after_days(), 21)
			self.assertEqual(settings.suspend_after_days(), 14)

	def test_overrides_nest_and_the_inner_one_wins_only_for_what_it_names(self):
		with billing_settings(suspend_after_days=14, terminate_after_days=44):
			with settings.overridden(suspend_after_days=21):
				with settings.overridden(terminate_after_days=60):
					self.assertEqual(settings.suspend_after_days(), 21)
					self.assertEqual(settings.terminate_after_days(), 60)

	def test_a_ladder_is_accepted_as_a_list_or_a_string(self):
		with settings.overridden(dunning_retry_days=[5, 2, 5]):
			self.assertEqual(settings.dunning_retry_days(), [2, 5])
		with settings.overridden(dunning_retry_days="10, 3"):
			self.assertEqual(settings.dunning_retry_days(), [3, 10])

	def test_what_is_being_pretended_can_be_reported(self):
		with settings.overridden(suspend_after_days=21):
			self.assertEqual(settings.active_overrides(), {"suspend_after_days": 21})
		self.assertEqual(settings.active_overrides(), {})


class ScenarioTestBase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		make_plan(PLAN)
		self._purge()
		self.sub = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		add_segment(self.sub, "Created", 5000, "2026-01-01 00:00:00")
		frappe.db.commit()

	def tearDown(self):
		self._purge()

	def _purge(self):
		for name in frappe.get_all("Billing Scenario", pluck="name"):
			frappe.delete_doc("Billing Scenario", name, force=True, ignore_permissions=True)
		frappe.db.delete("Invoice", {"team": TEAM})
		for sub in frappe.get_all("Subscription", {"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": sub})
			frappe.db.delete("Subscription", {"name": sub})
		frappe.db.delete("Asset", {"team": TEAM})
		frappe.db.commit()

	def _scenario(self, name="What if we dun harder", **kw):
		doc = frappe.get_doc(
			{
				"doctype": "Billing Scenario",
				"scenario_name": name,
				"team": TEAM,
				"period_start": "2026-09-01",
				"months": 1,
				"outcome_mode": "Derived",
				**kw,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		return doc


class TestProjectingUnderAScenario(ScenarioTestBase):
	def test_an_altered_ladder_moves_the_projected_dates(self):
		with billing_settings(
			dunning_retry_days="1, 3, 7", suspend_after_days=14, terminate_after_days=44
		):
			live = scenario.project(self._scenario("Live"), today=TODAY)
			altered = scenario.project(
				self._scenario("Harsher", scenario_name="Harsher", suspend_after_days=5),
				today=TODAY,
			)

		def suspend_on(out):
			return next(
				s["date"] for s in out["calendar"]["if_never_paid"] if s["stage"] == "Suspend"
			)

		self.assertNotEqual(suspend_on(live), suspend_on(altered))
		self.assertLess(suspend_on(altered), suspend_on(live))

	def test_a_scenario_reports_what_it_pretended(self):
		out = scenario.project(self._scenario(suspend_after_days=5), today=TODAY)
		self.assertEqual(out["scenario"]["overrides"], {"suspend_after_days": 5})

	def test_a_scenario_with_no_overrides_pretends_nothing(self):
		out = scenario.project(self._scenario(), today=TODAY)
		self.assertEqual(out["scenario"]["overrides"], {})

	def test_the_override_does_not_outlive_the_projection(self):
		with billing_settings(suspend_after_days=14):
			scenario.project(self._scenario(suspend_after_days=5), today=TODAY)
			self.assertEqual(settings.suspend_after_days(), 14)

	def test_a_multi_month_scenario_rolls_forward(self):
		out = scenario.project(self._scenario(months=3), today=TODAY)
		self.assertEqual(len(out["months"]), 3)

	def test_a_cohort_scenario_is_refused_here_rather_than_guessed_at(self):
		doc = self._scenario()
		doc.db_set("team", None)
		with self.assertRaises(frappe.ValidationError):
			scenario.project(doc.name, today=TODAY)


class TestSavingAScenario(ScenarioTestBase):
	def test_the_result_is_stored_and_reloadable(self):
		doc = self._scenario()
		out = scenario.project_and_save(doc.name, today=TODAY)

		reloaded = frappe.get_doc("Billing Scenario", doc.name)
		self.assertTrue(reloaded.projected_at)
		self.assertEqual(
			frappe.parse_json(reloaded.result)["invoice"]["total"], out["invoice"]["total"]
		)

	def test_reprojecting_the_same_scenario_gives_the_same_answer(self):
		doc = self._scenario()
		first = scenario.project(doc.name, today=TODAY)
		second = scenario.project(doc.name, today=TODAY)
		self.assertEqual(first["invoice"]["total"], second["invoice"]["total"])
		self.assertEqual(first["calendar"], second["calendar"])

	def test_saving_a_projection_writes_only_the_scenario(self):
		# The only thing between "saves a scenario" and "saves an invoice".
		doc = self._scenario()
		before = {
			dt: frappe.db.count(dt)
			for dt in ("Invoice", "Payment Attempt", "Credit Ledger Entry", "Subscription Change")
		}
		scenario.project_and_save(doc.name, today=TODAY)
		for dt, count in before.items():
			self.assertEqual(frappe.db.count(dt), count, dt)

	def test_the_writable_surface_is_exactly_one_doctype(self):
		self.assertEqual(set(scenario.WRITABLE), {"Billing Scenario"})

	def test_nothing_here_is_called_a_run(self):
		# "Run" means the monthly billing run. Nothing read-only borrows the word.
		meta = frappe.get_meta("Billing Scenario")
		names = [f.fieldname for f in meta.fields] + [meta.name]
		self.assertFalse([n for n in names if "run" in n.lower()])


class TestComparing(ScenarioTestBase):
	def test_live_and_altered_are_projected_by_the_same_engine(self):
		with billing_settings(suspend_after_days=14):
			out = scenario.compare(self._scenario(suspend_after_days=5), today=TODAY)

		self.assertTrue(out["changed"])
		self.assertEqual(out["live"]["invoice"]["total"], out["altered"]["invoice"]["total"])

		def suspend_on(side):
			return next(
				s["date"] for s in out[side]["calendar"]["if_never_paid"] if s["stage"] == "Suspend"
			)

		# Same bill, different consequence — which is exactly what the override changed.
		self.assertNotEqual(suspend_on("live"), suspend_on("altered"))

	def test_a_scenario_that_pretends_nothing_compares_to_itself(self):
		out = scenario.compare(self._scenario(), today=TODAY)
		self.assertFalse(out["changed"])
		self.assertEqual(out["live"]["calendar"], out["altered"]["calendar"])
