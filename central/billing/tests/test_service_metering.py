# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Consumer-service metered billing (ADR 0015): per-family settlement + reporting
mode, synthesized team-level subjects, dual-mode usage ingestion, and the
pilot-authenticated service API."""

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.catalog import subscriptions
from central.billing.tests.utils import complete_billing_profile, ensure_team, make_metered_plan


def _ensure_resource_type(name: str) -> str:
	"""A metered Plan's include links a Resource Type; ensure one exists for the test."""
	if not frappe.db.exists("Resource Type", name):
		frappe.get_doc({"doctype": "Resource Type", "resource_type_name": name}).insert(
			ignore_permissions=True
		)
	return name


class TestPlanCategoryModes(IntegrationTestCase):
	"""settlement_mode / reporting_mode are per-family properties, blank resolving to
	the built default; both are meaningless on a Fixed family (ADR 0015)."""

	def _category(self, name, billing_type="Metered", **kwargs):
		if frappe.db.exists("Plan Category", name):
			frappe.delete_doc("Plan Category", name, force=True)
		doc = frappe.get_doc(
			{"doctype": "Plan Category", "category_name": name, "billing_type": billing_type, **kwargs}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def test_blank_modes_resolve_to_built_defaults(self):
		cat = self._category("SM Metered Blank")
		self.assertEqual(cat.effective_settlement_mode, "Postpaid Overage")
		self.assertEqual(cat.effective_reporting_mode, "Authoritative")

	def test_explicit_modes_are_honoured(self):
		cat = self._category(
			"SM Prepaid Incremental",
			settlement_mode="Prepaid Pack",
			reporting_mode="Incremental",
		)
		self.assertEqual(cat.effective_settlement_mode, "Prepaid Pack")
		self.assertEqual(cat.effective_reporting_mode, "Incremental")

	def test_modes_cleared_on_fixed_family(self):
		cat = self._category(
			"SM Fixed Bundle",
			billing_type="Fixed",
			settlement_mode="Prepaid Pack",
			reporting_mode="Incremental",
		)
		# A bundle has no metered reporting — the controller blanks both on validate.
		self.assertFalse(cat.settlement_mode)
		self.assertFalse(cat.reporting_mode)
		self.assertEqual(cat.effective_settlement_mode, "Postpaid Overage")
		self.assertEqual(cat.effective_reporting_mode, "Authoritative")


class TestServiceSubjectProvisioning(IntegrationTestCase):
	"""A team-level service is subscribed with a synthesized subject and no Asset
	(ADR 0013): the segment opens inline and metering resolves it like any resource."""

	TEAM = "svc-team-a"

	def setUp(self):
		ensure_team(self.TEAM)
		complete_billing_profile(self.TEAM, currency="INR")
		frappe.db.delete("Subscription", {"team": self.TEAM})
		_ensure_resource_type("PDF Render")
		self.plan = make_metered_plan("Svc PDF Render", resource_type="PDF Render", unit="doc")

	def test_provision_synthesizes_subject_and_opens_segment(self):
		res = subscriptions.provision_service_subscription(self.TEAM, self.plan, cluster="mumbai")

		self.assertTrue(res["service_subject"].startswith("svc-"))
		self.assertFalse(res["reused"])
		self.assertEqual(res["currency"], "INR")

		sub = frappe.get_doc("Subscription", res["subscription"])
		self.assertEqual(sub.service_subject, res["service_subject"])
		self.assertFalse(sub.asset_id)  # no VM Asset for a team-level service
		self.assertEqual(sub.cluster, "mumbai")

		# Metering resolves the subject off the ledger, just like a VM resource.
		seg = subscriptions.active_segment_for_resource(res["service_subject"])
		self.assertIsNotNone(seg)
		self.assertEqual(seg.team, self.TEAM)
		self.assertEqual(seg.cluster, "mumbai")
		self.assertEqual(seg.currency, "INR")

	def test_reprovision_same_service_is_idempotent(self):
		first = subscriptions.provision_service_subscription(self.TEAM, self.plan, cluster="mumbai")
		second = subscriptions.provision_service_subscription(self.TEAM, self.plan, cluster="mumbai")

		self.assertEqual(first["service_subject"], second["service_subject"])
		self.assertEqual(first["subscription"], second["subscription"])
		self.assertTrue(second["reused"])
		self.assertEqual(
			frappe.db.count("Subscription", {"service_subject": first["service_subject"]}), 1
		)

	def test_different_cluster_is_a_distinct_subject(self):
		mumbai = subscriptions.provision_service_subscription(self.TEAM, self.plan, cluster="mumbai")
		blr = subscriptions.provision_service_subscription(self.TEAM, self.plan, cluster="blr")
		self.assertNotEqual(mumbai["service_subject"], blr["service_subject"])

	def test_server_plan_rejected_as_service(self):
		from central.billing.tests.utils import make_plan

		server_plan = make_plan("Svc Server Plan", rates=[{"cluster": "", "currency": "INR", "rate": 500}])
		frappe.db.set_value(
			"Plan Category", frappe.db.get_value("Plan", server_plan, "category"),
			"provision_target", "Server",
		)
		with self.assertRaises(frappe.ValidationError):
			subscriptions.provision_service_subscription(self.TEAM, server_plan, cluster="mumbai")
