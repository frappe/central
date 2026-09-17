from unittest.mock import patch

import frappe

from central.billing.catalog import subscriptions
from central.billing.tests.provisioning import create_billed_server
from central.billing.tests.utils import (
	BillingTestCase,
	complete_billing_profile,
	ensure_atlas_instance,
	ensure_team,
	make_plan,
	set_team_tier,
)
from central.integrations.server_provisioning import _process_locked

TEAM = "team-create-server"
REGION = "ap-south-1"


class TestCreateServerRecordsSubscription(BillingTestCase):
	_TRACKED = (*BillingTestCase._TRACKED, "Resource Action", "Pilot Credential")

	def setUp(self):
		self.team = "test-create-" + frappe.generate_hash(length=8)
		frappe.set_user("Administrator")
		ensure_atlas_instance(REGION)
		ensure_team(self.team)
		complete_billing_profile(self.team, currency="INR")
		set_team_tier(self.team, max_spend=100000)
		self.plan = make_plan(
			"bundle-create-server", rates=[{"cluster": "", "currency": "INR", "rate": 1500}]
		)

	def create(self, **changes):
		return create_billed_server(self.team, REGION, self.plan, **changes)

	def test_bundle_provision_records_subscription_and_lock(self):
		action, client = self.create()
		self.assertEqual(action.status, "Succeeded")
		subscription = frappe.get_doc("Subscription", {"asset_id": action.asset})
		self.assertEqual(
			(subscription.team, subscription.plan, subscription.pricing_mode),
			(self.team, self.plan, "Preset"),
		)
		self.assertEqual(subscriptions.current_segment_rate(subscription.name), 1500)
		self.assertEqual(frappe.db.count("Subscription", {"team": self.team, "asset_id": action.asset}), 1)
		asset = frappe.get_doc("Asset", action.asset)
		self.assertEqual(asset.plan, self.plan)
		self.assertEqual(asset.atlas_vm_id, "vm-billing-test")
		self.assertEqual((asset.vcpus, asset.memory_megabytes, asset.disk_gigabytes), (2, 4096, 80))
		client.create_vm.assert_called_once()

	def test_friendly_title_and_guest_hostname_are_separate(self):
		action, client = self.create(title="Acme Production 01", hostname="customer-portal")
		self.assertEqual(frappe.db.get_value("Asset", action.asset, "title"), "Acme Production 01")
		self.assertEqual(client.create_vm.call_args.args[0]["hostname"], "customer-portal")

	def test_plan_transfer_allowance_survives_provisioning(self):
		plan = frappe.get_doc("Plan", self.plan)
		plan.append("includes", {"resource_type": "Transfer", "quantity": 100, "unit": "GB"})
		plan.save()

		action, client = self.create()
		self.assertEqual(action.status, "Succeeded")
		configuration = action.get_configuration()
		transfer = next(row for row in configuration.includes if row.resource_type == "Transfer")
		self.assertEqual((transfer.quantity, transfer.unit), (100, "GB"))
		payload = client.create_vm.call_args.args[0]
		self.assertEqual((payload["vcpus"], payload["memory_mib"], payload["disk_mib"]), (2, 4096, 81920))

	def test_rejects_invalid_hostname_before_dispatch(self):
		with self.assertRaises(frappe.ValidationError):
			self.create(hostname="!!!")
		self.assertFalse(frappe.db.exists("Resource Action", {"team": self.team}))

	def test_rejects_overlong_title(self):
		with self.assertRaises(frappe.ValidationError):
			self.create(title="a" * 141)

	def test_unpriced_raw_server_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			create_billed_server(self.team, REGION, None)

	def test_refused_without_a_complete_billing_profile(self):
		frappe.db.delete("Billing Profile", {"team": self.team})
		with self.assertRaises(frappe.ValidationError):
			self.create()
		self.assertFalse(frappe.db.exists("Resource Action", {"team": self.team}))

	def test_pending_requests_reserve_spending_limit(self):
		set_team_tier(self.team, max_spend=2000)
		with patch("central.billing.tests.provisioning._process_locked"):
			first, _ = self.create()
			self.assertEqual(first.status, "Queued")
			with self.assertRaises(frappe.ValidationError):
				self.create()

	def test_billing_failure_preserves_remote_identity_for_recovery(self):
		with (
			patch(
				"central.integrations.server_provisioning._create_subscription",
				side_effect=RuntimeError("billing unavailable"),
			),
			patch("frappe.db.rollback"),
		):
			action, client = self.create()
		self.assertEqual(action.status, "Sent")
		self.assertEqual(action.error_code, "FINALIZATION_FAILED")
		self.assertEqual(action.remote_vm_id, "vm-billing-test")
		with (
			patch("central.integrations.server_provisioning._client", return_value=client),
			patch("central.integrations.server_provisioning.observe_server", return_value="Running"),
			patch("frappe.db.commit"),
		):
			_process_locked(action.name)
		self.assertEqual(action.reload().status, "Succeeded")
		client.create_vm.assert_called_once()
		self.assertEqual(frappe.db.count("Subscription", {"team": self.team, "asset_id": action.asset}), 1)

	def test_queued_creation_keeps_accepted_price_after_catalog_change(self):
		from central.billing.catalog.pricing import set_catalog_rate

		with patch("central.billing.tests.provisioning._process_locked"):
			action, client = self.create()
		set_catalog_rate("Plan", self.plan, "INR", 1900)
		with (
			patch("central.integrations.server_provisioning._client", return_value=client),
			patch("central.integrations.server_provisioning.observe_server", return_value="Running"),
			patch("frappe.db.commit"),
		):
			_process_locked(action.name)
		action.reload()
		self.assertEqual(action.status, "Succeeded")
		subscription = frappe.db.get_value("Subscription", {"asset_id": action.asset})
		self.assertEqual(subscriptions.current_segment_rate(subscription), 1500)
