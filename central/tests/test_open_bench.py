import frappe
import jwt
from frappe.tests import IntegrationTestCase
from jwt.algorithms import RSAAlgorithm

from central.api.jwks import jwks_document
from central.api.sso import get_bench_link
from central.central.doctype.central_sso_settings.central_sso_settings import ALGORITHM
from central.central.doctype.pilot_credential.pilot_credential import PilotCredential
from central.sso import central_url
from central.tests.test_iam import ensure_user

# Open-in-bench for a real VM (asset) now hands back a Central-signed admin SID as
# `{gateway}/?sid=<jwt>`. Central mints it locally against its RSA key, scoped to the bench's
# audience id (its pilot_credential_id); the bench verifies it offline against the JWKS. No
# Atlas round-trip: opening a Running VM on an Active cluster just needs a gateway + an
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
		self.asset = self._asset("vm-open-1", "Running")
		self.pcid = "pcred-open-1"
		self._credential(self.pcid, "vm-open-1")

	def tearDown(self):
		frappe.set_user("Administrator")

	def _credential(self, pcid, rid):
		"""An enrolled pilot bound to the VM — its audience_id is what SIDs are minted for."""
		if frappe.db.exists("Pilot Credential", pcid):
			frappe.delete_doc("Pilot Credential", pcid, force=True)
		PilotCredential.mint(team=self.team.name, pilot_credential_id=pcid, asset=rid, audience_id=pcid)

	def _team(self):
		name = "Open Bench Team"
		existing = frappe.db.get_value("Team", {"team_name": name})
		if existing:
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

	def _cluster(self, region):
		if not frappe.db.exists("Region", region):
			frappe.get_doc({"doctype": "Region", "region": region}).insert()
		if frappe.db.exists("Atlas Instance", region):
			frappe.delete_doc("Atlas Instance", region, force=True)
		frappe.get_doc(
			{
				"doctype": "Atlas Instance",
				"region": region,
				"base_url": "https://atlas.example.test",
				"status": "Active",
				"api_key": "k",
				"api_secret": "s",
			}
		).insert()
		return region

	def _asset(self, rid, status, *, gateway=GATEWAY):
		if frappe.db.exists("Asset", rid):
			frappe.delete_doc("Asset", rid, force=True, ignore_permissions=True)
		return frappe.get_doc(
			{
				"doctype": "Asset",
				"resource_id": rid,
				"team": self.team.name,
				"cluster": self.cluster,
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
		link = self._open(self.dev, asset="vm-open-1")
		self.assertTrue(link["url"].startswith(f"{GATEWAY}/?sid="))

		public_key = RSAAlgorithm.from_jwk(jwks_document()["keys"][0])
		claims = jwt.decode(
			link["url"].split("sid=", 1)[1],
			public_key,
			algorithms=[ALGORITHM],
			audience=self.pcid,
			issuer=central_url(),
		)
		self.assertEqual(claims["sub"], "admin")
		self.assertEqual(claims["scope"], "bench")

	def test_unenrolled_vm_refused(self):
		"""A Running VM whose pilot hasn't enrolled has no audience id yet — Open is refused
		rather than minting a SID no bench would accept."""
		frappe.delete_doc("Pilot Credential", self.pcid, force=True)
		with self.assertRaises(frappe.ValidationError):
			self._open(self.dev, asset="vm-open-1")

	def test_viewer_without_vm_open_is_blocked(self):
		with self.assertRaises(frappe.PermissionError):
			self._open(self.viewer, asset="vm-open-1")

	def test_stopped_vm_refused(self):
		self._asset("vm-open-1", "Stopped")
		with self.assertRaises(frappe.ValidationError):
			self._open(self.dev, asset="vm-open-1")

	def test_missing_gateway_refused(self):
		self._asset("vm-open-1", "Running", gateway=None)
		with self.assertRaises(frappe.ValidationError):
			self._open(self.dev, asset="vm-open-1")

	def test_disabled_cluster_refused(self):
		frappe.db.set_value("Atlas Instance", self.cluster, "status", "Disabled")
		with self.assertRaises(frappe.ValidationError):
			self._open(self.dev, asset="vm-open-1")
