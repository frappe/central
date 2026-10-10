import frappe
import jwt
from frappe.tests import IntegrationTestCase

from central.api.jwks import jwks_document
from central.api.sso import get_bench_link
from central.central.doctype.central_sso_settings.central_sso_settings import ALGORITHM, CentralSSOSettings
from central.infrastructure.doctype.pilot_credential.pilot_credential import PilotCredential
from central.sso import central_url
from central.tests.test_iam import ensure_user

# Open-in-bench for a real VM (server) now hands back a Central-signed admin SID as
# `{gateway}/?sid=<jwt>`. Central mints it locally against its Pilot key, scoped to the bench's
# audience id (its pilot_credential_id); the bench verifies it offline against the JWKS. No
# Atlas round-trip: opening a Running VM in an active region just needs a gateway + an
# enrolled pilot. The SID is single-use (jti + short TTL), so a fresh one is minted on every Open.

GATEWAY = "https://vm-open-1.blr1.frappe.dev"


class TestOpenBench(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = ensure_user("open.owner@example.test")
		self.dev = ensure_user("open.dev@example.test")
		self.viewer = ensure_user("open.viewer@example.test")
		self.team = self._team()
		self.cluster = self._cluster("blr-open")
		self.server = self._server("vm-open-1", "Running")
		self.pcid = "pcred-open-1"
		self._credential(self.pcid, "vm-open-1")
		CentralSSOSettings.instance().initialize_signing_key("pilot")

	def tearDown(self):
		frappe.set_user("Administrator")
		self._clear_team(self.team.name)
		frappe.delete_doc("Team", self.team.name, force=True, ignore_permissions=True)

	def _credential(self, pcid, rid):
		"""An enrolled pilot bound to the VM — its audience_id is what SIDs are minted for."""
		if frappe.db.exists("Pilot Credential", pcid):
			frappe.delete_doc("Pilot Credential", pcid, force=True)
		PilotCredential.mint(team=self.team.name, pilot_credential_id=pcid, server=rid, audience_id=pcid)

	def _team(self):
		name = "Open Bench Team"
		existing = frappe.db.get_value("Team", {"team_name": name})
		if existing:
			self._clear_team(existing)
			frappe.delete_doc("Team", existing, force=True, ignore_permissions=True)
		return frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": name,
				"owner_user": self.owner,
				"members": [
					{"user": self.owner, "role": "Owner", "status": "Active"},
					{"user": self.dev, "role": "Developer", "status": "Active"},
					{"user": self.viewer, "role": "Viewer", "status": "Active"},
				],
			}
		).insert()

	def _clear_team(self, team):
		for credential in frappe.get_all("Pilot Credential", filters={"team": team}, pluck="name"):
			frappe.delete_doc("Pilot Credential", credential, force=True, ignore_permissions=True)
		for site in frappe.get_all("Site", filters={"team": team}, pluck="name"):
			frappe.delete_doc("Site", site, force=True, ignore_permissions=True)
		for server in frappe.get_all("Virtual Machine", filters={"team": team}, pluck="name"):
			frappe.delete_doc("Virtual Machine", server, force=True, ignore_permissions=True)

	def _cluster(self, region):
		if frappe.db.exists("Region", region):
			frappe.delete_doc("Region", region, force=True)
		frappe.get_doc(
			{
				"doctype": "Region",
				"region": region,
				"base_url": "https://atlas.example.test",
				"status": "Active",
			}
		).insert()
		return region

	def _server(self, rid, status, *, gateway=GATEWAY):
		if frappe.db.exists("Virtual Machine", rid):
			frappe.delete_doc("Virtual Machine", rid, force=True, ignore_permissions=True)
		return frappe.get_doc(
			{
				"doctype": "Virtual Machine",
				"resource_id": rid,
				"team": self.team.name,
				"region": self.cluster,
				"status": status,
				"gateway_url": gateway or None,
			}
		).insert(ignore_permissions=True)

	def _open(self, user, **kwargs):
		frappe.set_user(user)
		try:
			return get_bench_link(**kwargs)
		finally:
			frappe.set_user("Administrator")

	def test_open_running_vm_mints_local_sid(self):
		"""Opening a Running VM returns a Central-signed SID at the VM's gateway, scoped to
		the bench's audience id (its pilot_credential_id) — verifiable against the JWKS, with
		no Atlas call."""
		link = self._open(self.dev, server="vm-open-1")
		self.assertTrue(link["url"].startswith(f"{GATEWAY}/?sid="))

		public_key = jwt.PyJWK.from_dict(jwks_document()["keys"][0]).key
		claims = jwt.decode(
			link["url"].split("sid=", 1)[1],
			public_key,
			algorithms=[ALGORITHM],
			audience=self.pcid,
			issuer=central_url(),
		)
		self.assertEqual(claims["sub"], "admin")
		self.assertEqual(claims["scope"], "bench")

	def test_an_operator_opens_the_bench_and_the_server_records_it(self):
		url = frappe.get_doc("Virtual Machine", "vm-open-1").open_bench_as_administrator()

		self.assertTrue(url.startswith(f"{GATEWAY}/?sid="))
		self.assertTrue(
			frappe.db.exists(
				"Comment",
				{
					"reference_doctype": "Virtual Machine",
					"reference_name": "vm-open-1",
					"content": ("like", "%as Administrator%"),
				},
			)
		)

	def test_only_an_operator_opens_the_bench_from_desk(self):
		frappe.set_user(self.owner)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("Virtual Machine", "vm-open-1").open_bench_as_administrator()

	def test_unenrolled_vm_refused(self):
		"""A Running VM whose pilot hasn't enrolled has no audience id yet — Open is refused
		rather than minting a SID no bench would accept."""
		frappe.delete_doc("Pilot Credential", self.pcid, force=True)
		with self.assertRaises(frappe.ValidationError):
			self._open(self.dev, server="vm-open-1")

	def test_a_viewer_cannot_open_the_bench_as_admin(self):
		with self.assertRaises(frappe.PermissionError):
			self._open(self.viewer, server="vm-open-1")

	def test_local_gateway_uses_the_servers_pilot_audience(self):
		self._server("vm-open-1", "Running", gateway="http://localhost:3030")
		link = self._open(self.dev, server="vm-open-1")
		self.assertTrue(link["url"].startswith("http://localhost:3030/?sid="))

		public_key = jwt.PyJWK.from_dict(jwks_document()["keys"][0]).key
		claims = jwt.decode(
			link["url"].split("sid=", 1)[1],
			public_key,
			algorithms=[ALGORITHM],
			audience=self.pcid,
			issuer=central_url(),
		)
		self.assertEqual(claims["aud"], self.pcid)

	def test_stopped_vm_refused(self):
		self._server("vm-open-1", "Stopped")
		with self.assertRaises(frappe.ValidationError):
			self._open(self.dev, server="vm-open-1")

	def test_missing_gateway_refused(self):
		self._server("vm-open-1", "Running", gateway=None)
		with self.assertRaises(frappe.ValidationError):
			self._open(self.dev, server="vm-open-1")

	def test_disabled_cluster_refused(self):
		frappe.db.set_value("Region", self.cluster, "status", "Disabled")
		with self.assertRaises(frappe.ValidationError):
			self._open(self.dev, server="vm-open-1")
