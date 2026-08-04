# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""A seeded billing run at scale — the only honest answer to "will it hold up".

Sized by `SCALE_TEAMS` so the same test is a quick regression guard by default and a
real load run before a release. `SCALE_BUDGET_MS` is the per-team wall-clock ceiling.

Measured at 1000 teams on a dev bench: ~14ms per team to draft, in one process. The
budget is deliberately far above that — it is there to catch a regression into a
per-team query, not to benchmark the machine.
"""

import os
import time

import frappe

from central.billing.platform import invariants
from central.billing.revenue import invoicing
from central.billing.revenue.invoicing import run as run_module
from central.billing.tests.utils import (
	BillingTestCase,
	add_segment,
	ensure_team,
	make_billing_subscription,
	make_plan,
	purge_teams,
)

TEAMS = int(os.environ.get("SCALE_TEAMS", 40))
BUDGET_MS = int(os.environ.get("SCALE_BUDGET_MS", 400))
PERIOD = ("2026-06-01", "2026-06-30")
CLUSTER = "ap-south-1"
PLAN = "bundle-scale-test"


class TestBillingRunAtScale(BillingTestCase):
	def setUp(self):
		make_plan(PLAN)
		self.teams = [f"team-scale-{i:05d}" for i in range(TEAMS)]
		self._purge()
		for team in self.teams:
			ensure_team(team)
			sub = make_billing_subscription(team, CLUSTER, PLAN, billing_cycle="Monthly")
			add_segment(sub, "Created", 1000, f"{PERIOD[0]} 00:00:00")
		frappe.db.commit()

	def tearDown(self):
		self._purge()

	def _purge(self):
		# The run commits per team, so nothing rolls back on its own.
		purge_teams(self.teams)
		frappe.db.commit()

	def _my_invoices(self) -> list[str]:
		return frappe.get_all("Invoice", filters={"team": ["in", self.teams]}, pluck="name")

	def test_drafting_stays_inside_its_per_team_budget(self):
		started = time.monotonic()
		invoicing.generate_draft_invoices(*PERIOD)
		elapsed_ms = (time.monotonic() - started) * 1000

		self.assertEqual(len(self._my_invoices()), TEAMS)
		per_team = elapsed_ms / TEAMS
		self.assertLess(
			per_team,
			BUDGET_MS,
			f"drafting cost {per_team:.0f}ms/team, over the {BUDGET_MS}ms budget",
		)

	def test_a_full_run_leaves_every_money_invariant_holding(self):
		invoicing.generate_draft_invoices(*PERIOD)
		invoicing.open_drafts(PERIOD[1])

		mine = set(self.teams)
		violations = [v for v in invariants.audit() if v.team in mine]
		self.assertEqual(violations, [], f"scale run broke {len(violations)} invariant(s)")

	def test_a_run_killed_half_way_resumes_without_double_billing(self):
		half = self.teams[len(self.teams) // 2 - 1]
		run_module.draft_team_page("", half, *PERIOD)
		drafted_before = len(self._my_invoices())
		self.assertGreater(drafted_before, 0)
		self.assertLess(drafted_before, TEAMS)

		# The worker "dies" here. Nothing tracks where it got to, so the resumed run
		# simply re-walks everything and relies on drafting being idempotent.
		invoicing.generate_draft_invoices(*PERIOD)

		self.assertEqual(len(self._my_invoices()), TEAMS)
		for team in self.teams:
			self.assertEqual(frappe.db.count("Invoice", {"team": team}), 1)

	def test_progress_is_read_from_the_tables_not_a_counter(self):
		run_module.draft_team_page("", self.teams[len(self.teams) // 2 - 1], *PERIOD)
		status = run_module.billing_run_status("2026-07-01")

		# Derived, so a half-finished run reports itself as half finished.
		self.assertGreaterEqual(status["drafted"], len(self._my_invoices()))
		self.assertGreater(status["pending_draft"], 0)

	def test_collection_settles_every_draft_it_finds(self):
		invoicing.generate_draft_invoices(*PERIOD)
		invoicing.open_drafts(PERIOD[1])

		still_draft = frappe.db.count("Invoice", {"team": ["in", self.teams], "status": "Draft"})
		self.assertEqual(still_draft, 0)
