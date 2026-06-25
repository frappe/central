import frappe
from frappe.tests import IntegrationTestCase

from central.billing.tests.utils import make_plan
from central.tests.test_iam import ensure_user


class TestAsset(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = ensure_user("asset.owner@example.test")
		self.team = frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": "Asset Team",
				"owner_user": self.owner,
				"members": [{"user": self.owner, "role": "Owner", "status": "Active"}],
			}
		).insert()
		self.cluster = "blr-asset"
		if not frappe.db.exists("Atlas Instance", self.cluster):
			frappe.get_doc(
				{
					"doctype": "Atlas Instance",
					"region": self.cluster,
					"base_url": "https://atlas.example.test",
					"status": "Active",
					"api_key": "k",
					"api_secret": "s",
				}
			).insert()

	def test_asset_named_by_resource_id_and_links(self):
		asset = frappe.get_doc(
			{
				"doctype": "Asset",
				"resource_id": "vm-xyz",
				"team": self.team.name,
				"cluster": self.cluster,
				"status": "Running",
				"gateway_url": "http://localhost:3030",
			}
		).insert()
		self.assertEqual(asset.name, "vm-xyz")
		self.assertEqual(asset.team, self.team.name)
		self.assertEqual(asset.cluster, self.cluster)


class TestAssetSubscriptionSync(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = ensure_user("asset.sub.owner@example.test")
		self.team = frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": "Asset Sub Team",
				"owner_user": self.owner,
				"members": [{"user": self.owner, "role": "Owner", "status": "Active"}],
			}
		).insert().name
		self.cluster = "blr-asset-sub"
		if not frappe.db.exists("Atlas Instance", self.cluster):
			frappe.get_doc(
				{
					"doctype": "Atlas Instance",
					"region": self.cluster,
					"base_url": "https://atlas.example.test",
					"status": "Active",
					"api_key": "k",
					"api_secret": "s",
				}
			).insert()
		self.plan_a = make_plan("plan-asset-sub-a")
		self.plan_b = make_plan("plan-asset-sub-b")
		self._assets = []

	def tearDown(self):
		for resource_id in self._assets:
			for change in frappe.get_all(
				"Subscription Change",
				filters={"subscription": ["in", frappe.get_all(
					"Subscription", filters={"team": self.team, "asset_id": resource_id}, pluck="name"
				)]},
				pluck="name",
			):
				frappe.delete_doc("Subscription Change", change, force=True)
			for sub in frappe.get_all("Subscription", filters={"team": self.team, "asset_id": resource_id}, pluck="name"):
				frappe.delete_doc("Subscription", sub, force=True)
			frappe.delete_doc("Asset", resource_id, force=True)

	def _make_asset(self, resource_id, status="Pending", plan=None):
		self._assets.append(resource_id)
		return frappe.get_doc(
			{
				"doctype": "Asset",
				"resource_id": resource_id,
				"team": self.team,
				"cluster": self.cluster,
				"status": status,
				"plan": plan or self.plan_a,
			}
		).insert()

	def _subscription_for(self, resource_id):
		return frappe.db.get_value("Subscription", {"team": self.team, "asset_id": resource_id}, "name")

	def test_running_status_creates_subscription_when_missing(self):
		asset = self._make_asset("vm-sub-create", status="Pending")
		asset.status = "Running"
		asset.save()

		sub_name = self._subscription_for(asset.name)
		self.assertTrue(sub_name)
		self.assertEqual(frappe.db.get_value("Subscription", sub_name, "enabled"), 1)
		self.assertEqual(frappe.db.get_value("Subscription", sub_name, "plan"), self.plan_a)

	def test_running_status_enables_existing_disabled_subscription(self):
		asset = self._make_asset("vm-sub-enable", status="Running")
		sub_name = self._subscription_for(asset.name)
		frappe.db.set_value("Subscription", sub_name, "enabled", 0)

		# Cycle status away and back to Running to re-trigger the sync.
		asset.reload()
		asset.status = "Stopped"
		asset.save()
		asset.status = "Running"
		asset.save()

		self.assertEqual(frappe.db.get_value("Subscription", sub_name, "enabled"), 1)

	def test_terminated_status_disables_active_subscription(self):
		asset = self._make_asset("vm-sub-terminate", status="Running")
		sub_name = self._subscription_for(asset.name)

		asset.status = "Terminated"
		asset.save()

		self.assertEqual(frappe.db.get_value("Subscription", sub_name, "enabled"), 0)

	def test_plan_change_while_running_updates_subscription_plan(self):
		asset = self._make_asset("vm-sub-plan", status="Running", plan=self.plan_a)
		sub_name = self._subscription_for(asset.name)

		asset.plan = self.plan_b
		asset.save()

		self.assertEqual(frappe.db.get_value("Subscription", sub_name, "plan"), self.plan_b)
		changes = frappe.get_all(
			"Subscription Change",
			filters={"subscription": sub_name, "change_type": "Plan Changed"},
			fields=["old_value", "new_value"],
		)
		self.assertEqual(len(changes), 1)
		self.assertEqual(changes[0].old_value, self.plan_a)
		self.assertEqual(changes[0].new_value, self.plan_b)
