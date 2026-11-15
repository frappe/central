from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from central.infrastructure.doctype.site_domain.site_domain import SiteDomain
from central.integrations.object_storage import ObjectStorageRejected
from central.integrations.pilot import sync_bucket_origins
from central.services.doctype.team_service.team_service import get_bucket_name
from central.tests.test_iam import ensure_user
from central.tests.utils import ensure_atlas_instance

PILOT = "central.integrations.pilot"
WILDCARD = "example.test"


class TestBucketOrigins(IntegrationTestCase):
	"""The sites of a server with a backup bucket may call that bucket from a browser."""

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.set_single_value("Central Settings", "wildcard_domain", WILDCARD)
		self.suffix = frappe.generate_hash(length=8)
		self.zone = f"bo-{self.suffix}.{WILDCARD}"
		self.region = ensure_atlas_instance(f"bo-{self.suffix}", proxy_domain=self.zone)
		owner = ensure_user("bucket.origins.owner@example.test")
		self.team = (
			frappe.get_doc(
				{
					"doctype": "Team",
					"team_name": f"Bucket Origins {self.suffix}",
					"owner_user": owner,
					"members": [{"user": owner, "role": "Owner", "status": "Active"}],
				}
			)
			.insert()
			.name
		)
		self.server = frappe.get_doc(
			{
				"doctype": "Virtual Machine",
				"resource_id": f"vm-bo-{self.suffix}",
				"team": self.team,
				"region": self.region,
				"status": "Running",
				"ipv6_address": "2001:db8::20",
			}
		).insert(ignore_permissions=True)
		self.bucket = get_bucket_name(self.team, self.region, self.server.name)

		self.cargo = MagicMock()
		self.cargo.set_allowed_origins.side_effect = lambda name, origins: {"allowed_origins": origins}
		client = self.enterContext(patch(f"{PILOT}.ObjectStorageClient"))
		client.from_region.return_value = self.cargo
		self.has_bucket = self.enterContext(patch(f"{PILOT}.has_bundled_bucket", return_value=True))
		self.queued_servers = []
		self.enterContext(patch(f"{PILOT}.frappe.enqueue", side_effect=self._queue))
		self.enterContext(patch.object(SiteDomain, "after_insert"))
		self.proxy = self.enterContext(
			patch("central.infrastructure.doctype.site_domain.site_domain.Region.get_proxy_client")
		).return_value

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_the_site_and_its_active_domains_are_sent(self):
		site = self._site()
		shop = self._route(f"shop-{self.suffix}.com")
		self._route(f"pending-{self.suffix}.com", apply=False)

		self._run_queued_jobs()

		self.cargo.set_allowed_origins.assert_called_with(
			self.bucket, sorted([f"https://{site.name}", f"https://{shop.name}"])
		)

	def test_a_domain_change_sends_the_new_list(self):
		site = self._site()
		self.assertEqual(self._sent(), [f"https://{site.name}"])

		shop = self._route(f"shop-{self.suffix}.com")
		self.assertEqual(self._sent(), sorted([f"https://{site.name}", f"https://{shop.name}"]))

		frappe.delete_doc("Site Domain", shop.name, ignore_permissions=True)
		self.assertEqual(self._sent(), [f"https://{site.name}"])

	def test_a_repeated_apply_of_an_active_domain_sends_nothing(self):
		shop = self._route(f"shop-{self.suffix}.com")
		self._run_queued_jobs()
		self.cargo.reset_mock()

		shop.reload()
		shop.apply()
		self._run_queued_jobs()

		self.cargo.set_allowed_origins.assert_not_called()

	def test_a_server_without_a_bucket_is_left_alone(self):
		self.has_bucket.return_value = False

		self._site()
		self._route(f"shop-{self.suffix}.com")
		self._run_queued_jobs()

		self.cargo.set_allowed_origins.assert_not_called()

	def test_a_refusal_keeps_the_route_and_tells_the_operator(self):
		self.cargo.set_allowed_origins.side_effect = ObjectStorageRejected("Garage is older than v2.3.0.")

		shop = self._route(f"shop-{self.suffix}.com")
		self._run_queued_jobs()

		self.assertEqual(frappe.db.get_value("Site Domain", shop.name, "status"), "Active")
		comments = frappe.get_all(
			"Comment",
			filters={"reference_doctype": "Virtual Machine", "reference_name": self.server.name},
			pluck="content",
		)
		self.assertIn("Central could not send this server's web addresses to its backup bucket.", comments)
		with self.assertRaises(ObjectStorageRejected):
			self.server.send_bucket_origins()

	def _queue(self, method, **kwargs):
		if method == f"{PILOT}.sync_bucket_origins":
			self.queued_servers.append(kwargs["server"])

	def _run_queued_jobs(self):
		"""Run the origins jobs, as the worker would after commit."""
		while self.queued_servers:
			sync_bucket_origins(self.queued_servers.pop(0))

	def _sent(self) -> list[str]:
		self._run_queued_jobs()
		return self.cargo.set_allowed_origins.call_args.args[1]

	def _site(self):
		return frappe.get_doc(
			{
				"doctype": "Site",
				"site_name": f"site-{self.suffix}.{self.zone}",
				"team": self.team,
				"server": self.server.name,
			}
		).insert(ignore_permissions=True)

	def _route(self, domain: str, apply: bool = True):
		route = frappe.get_doc(
			{
				"doctype": "Site Domain",
				"domain": domain,
				"team": self.team,
				"region": self.region,
				"server": self.server.name,
			}
		).insert(ignore_permissions=True)
		if apply:
			route.apply()
		return route
