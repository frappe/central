# Copyright (c) 2026, frappe and Contributors
# See license.txt

import math
import random
from unittest.mock import MagicMock, patch

import frappe
import jwt
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, now_datetime, set_request

from central.api.pilot import (
	datum_token,
	heartbeat,
	pilot_release,
	report_pilot_update,
	storage_regions,
)
from central.central.doctype.central_sso_settings.central_sso_settings import CentralSSOSettings
from central.infrastructure.doctype.pilot_credential.pilot_credential import PilotCredential
from central.sso import DATUM_SCOPE
from central.tests.test_iam import ensure_user
from central.tests.utils import ensure_atlas_instance


class TestPilotAPI(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = ensure_user("bench.api.owner@example.test")
		self.team = (
			frappe.get_doc(
				{
					"doctype": "Team",
					"team_name": "Bench API Team",
					"owner_user": self.owner,
					"members": [{"user": self.owner, "role": "Owner", "status": "Active"}],
				}
			)
			.insert()
			.name
		)
		self.token = PilotCredential.mint(team=self.team, pilot_credential_id="api-pilot-1")
		# A datum token is signed with the regional key, which an operator initializes once.
		CentralSSOSettings.instance().initialize_atlas_signing_key()

	def call_heartbeat(self, token: str | None) -> dict:
		"""Invoke the endpoint as a bench would: an X-Pilot-Token header, or none."""
		headers = {"X-Pilot-Token": token} if token is not None else {}
		set_request(method="GET", path="/api/method/central.api.pilot.heartbeat", headers=headers)
		return heartbeat()

	def test_valid_token_resolves_team_and_bench(self):
		result = self.call_heartbeat(self.token)
		self.assertTrue(result["ok"])
		self.assertEqual(result["team"], self.team)
		self.assertEqual(result["pilot_credential_id"], "api-pilot-1")

	def test_missing_header_is_rejected(self):
		with self.assertRaises(frappe.AuthenticationError):
			self.call_heartbeat(None)

	def test_garbage_token_is_rejected(self):
		with self.assertRaises(frappe.AuthenticationError):
			self.call_heartbeat("not-a-real-token")

	def test_revoked_token_is_rejected(self):
		frappe.get_doc("Pilot Credential", "api-pilot-1").revoke()
		with self.assertRaises(frappe.AuthenticationError):
			self.call_heartbeat(self.token)

	def test_expired_token_is_rejected(self):
		bench = frappe.get_doc("Pilot Credential", "api-pilot-1")
		bench.db_set("expires_at", add_to_date(now_datetime(), hours=-1))
		with self.assertRaises(frappe.AuthenticationError):
			self.call_heartbeat(self.token)

	def bound_pilot(self, region_id: int | None = None) -> str:
		"""A pilot with a Virtual Machine in a region, which is what a datum token is addressed to.

		The region id is unique per Region, so each test gets its own rather than
		colliding with whatever the site already holds."""
		self.region = f"tel-{frappe.generate_hash(length=6)}"
		ensure_atlas_instance(self.region, atlas_region_id=str(region_id or random.randint(1, 65535)))
		server = frappe.get_doc(
			{
				"doctype": "Virtual Machine",
				"resource_id": f"vm-{self.region}",
				"team": self.team,
				"region": self.region,
				"status": "Running",
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Pilot Credential", "api-pilot-1", "server", server.name)

		return server.name

	def reporting_region(self, service_endpoint: str, status: str = "Available") -> str:
		"""A bound pilot whose region has reported where its telemetry host serves."""
		self.bound_pilot()
		frappe.get_doc(
			{
				"doctype": "Service Detail",
				"region": self.region,
				"service": "telemetry",
				"status": status,
				"service_endpoint": service_endpoint,
			}
		).insert(ignore_permissions=True)

		return f"{self.region}-telemetry"

	def test_token_names_the_regional_telemetry_endpoint(self):
		"""The pilot is told where to ship without being told which region it is in: the
		The Virtual Machine links to its region, whose report names the host."""
		self.reporting_region("https://datum.example.test")

		self.assertEqual(self.call_datum_token(self.token)["endpoint"], "https://datum.example.test")

	def test_a_region_reporting_itself_down_hands_out_no_endpoint(self):
		"""Shipping at a host that says it is down only loses the rows. The token is still
		minted -- it is the endpoint that is missing, not the pilot's right to telemetry."""
		self.reporting_region("https://datum.example.test", status="Not Available")

		result = self.call_datum_token(self.token)
		self.assertIsNone(result["endpoint"])
		self.assertTrue(result["token"])

	def test_a_region_that_has_never_reported_hands_out_no_endpoint(self):
		"""No row at all, which is where every region starts."""
		self.bound_pilot()

		self.assertIsNone(self.call_datum_token(self.token)["endpoint"])

	def test_an_unbound_pilot_gets_no_token_at_all(self):
		"""No VirtualMachine means no resource to attribute rows to, so the mint is refused before
		the region is ever resolved."""
		self.reporting_region("https://datum.example.test")
		frappe.db.set_value("Pilot Credential", "api-pilot-1", "server", None)

		with self.assertRaises(frappe.ValidationError):
			self.call_datum_token(self.token)

	def call_datum_token(self, token: str | None) -> dict:
		headers = {"X-Pilot-Token": token} if token is not None else {}
		set_request(method="GET", path="/api/method/central.api.pilot.datum_token", headers=headers)
		return datum_token()

	def test_the_token_carries_the_scope_resource_and_write_access(self):
		"""Datum stamps every row with `resource_id` and reads both claims off the token
		through `Identity.from_claims`. Nothing sits in front of it to translate one."""
		server = self.bound_pilot()

		claims = jwt.decode(self.call_datum_token(self.token)["token"], options={"verify_signature": False})

		self.assertEqual(claims["scope"], DATUM_SCOPE)
		self.assertEqual(claims["resource_id"], server)
		self.assertEqual(claims["access"], ["write"])
		self.assertNotIn("vm_access", claims)

	def test_the_token_is_addressed_to_the_pilots_own_region(self):
		"""Every region reads the same key set, so the audience is what keeps a pilot
		from writing to another region's datum."""
		self.bound_pilot(region_id=7)

		claims = jwt.decode(self.call_datum_token(self.token)["token"], options={"verify_signature": False})

		self.assertEqual(claims["aud"], "atlas-datum:7")

	def test_the_token_is_signed_for_the_key_set_datum_reads(self):
		"""Datum fetches the merged set, which carries Ed25519 keys namespaced by issuer."""
		self.bound_pilot()

		token = self.call_datum_token(self.token)["token"]

		self.assertEqual(jwt.get_unverified_header(token)["alg"], "EdDSA")
		self.assertTrue(jwt.get_unverified_header(token)["kid"].startswith("central:"))
		self.assertEqual(jwt.decode(token, options={"verify_signature": False})["iss"], "central")

	def test_each_mint_is_its_own_credential(self):
		"""One route, but not one token: a pilot re-fetching gets a fresh credential, so
		one expiring or being replayed says nothing about the last."""
		self.bound_pilot()

		first = jwt.decode(self.call_datum_token(self.token)["token"], options={"verify_signature": False})
		second = jwt.decode(self.call_datum_token(self.token)["token"], options={"verify_signature": False})

		self.assertNotEqual(first["jti"], second["jti"])
		for claim in ("iss", "sub", "aud", "scope", "resource_id", "access"):
			self.assertEqual(first[claim], second[claim])

	def test_the_token_waits_for_the_resource(self):
		"""Atlas binds the VirtualMachine after provisioning; before that the rows would carry
		no resource id."""
		with self.assertRaises(frappe.ValidationError):
			self.call_datum_token(self.token)

	def call_storage_regions(self, token: str | None) -> dict:
		headers = {"X-Pilot-Token": token} if token is not None else {}
		set_request(method="GET", path="/api/method/central.api.pilot.storage_regions", headers=headers)
		return storage_regions()

	def test_storage_regions_lists_only_regions_serving_storage(self):
		serving = f"s3-{frappe.generate_hash(length=6)}"
		down = f"s3-{frappe.generate_hash(length=6)}"
		for region, status in ((serving, "Available"), (down, "Not Available")):
			ensure_atlas_instance(region, atlas_region_id=str(random.randint(1, 65535)))
			frappe.get_doc(
				{
					"doctype": "Service Detail",
					"region": region,
					"service": "storage",
					"status": status,
					"service_endpoint": f"https://s3.{region}.example.test",
				}
			).insert(ignore_permissions=True)

		regions = self.call_storage_regions(self.token)

		self.assertEqual(regions[serving], f"https://s3.{serving}.example.test")
		self.assertNotIn(down, regions)

	def test_storage_regions_needs_a_pilot_credential(self):
		with self.assertRaises(frappe.AuthenticationError):
			self.call_storage_regions(None)

	def set_rollout(
		self, tag: str = "", percent: int = 0, halted: bool = False, assets=("pilot.tar.gz",)
	) -> None:
		"""Save the rollout as an operator would; GitHub answers with a release holding `assets`,
		or a 404 when `assets` is None."""
		github = MagicMock(ok=assets is not None)
		github.json.return_value = {"assets": [{"name": name} for name in assets or ()]}
		settings = frappe.get_single("Central Settings")
		settings.update(
			{"pilot_release_tag": tag, "pilot_rollout_percent": percent, "pilot_rollout_halted": halted}
		)
		with patch(
			"central.central.doctype.central_settings.central_settings.requests.get", return_value=github
		):
			settings.save()

	def call_pilot_release(self, channel: str = "normal") -> dict:
		set_request(
			method="GET",
			path="/api/method/central.api.pilot.pilot_release",
			headers={"X-Pilot-Token": self.token},
		)
		return pilot_release(channel=channel)

	def test_no_tag_leaves_the_pilot_on_github(self):
		self.set_rollout()
		self.assertEqual(self.call_pilot_release(), {"tag": None})

	def test_percent_zero_and_full_release(self):
		self.set_rollout("v1", percent=0)
		self.assertEqual(self.call_pilot_release(), {"tag": "v1", "allowed": False})

		self.set_rollout("v1", percent=100)
		self.assertEqual(self.call_pilot_release(), {"tag": "v1", "allowed": True})

	def test_early_goes_first_and_late_waits(self):
		self.set_rollout("v1", percent=50)
		self.assertTrue(self.call_pilot_release("early")["allowed"])
		self.assertFalse(self.call_pilot_release("late")["allowed"])

	def test_halt_stops_everyone(self):
		self.set_rollout("v1", percent=100, halted=True)
		for channel in ("early", "normal", "late"):
			self.assertFalse(self.call_pilot_release(channel)["allowed"])

	def test_the_group_is_stable_per_tag_and_reshuffles_per_release(self):
		settings = frappe.get_single("Central Settings")
		settings.pilot_rollout_percent = 50
		pilots = [f"pcred-{number}" for number in range(200)]

		settings.pilot_release_tag = "v1"
		first = [settings.is_pilot_release_allowed(pilot, "normal") for pilot in pilots]
		self.assertEqual(first, [settings.is_pilot_release_allowed(pilot, "normal") for pilot in pilots])

		settings.pilot_release_tag = "v2"
		self.assertNotEqual(first, [settings.is_pilot_release_allowed(pilot, "normal") for pilot in pilots])

	def test_a_tag_that_is_not_a_pilot_release_is_refused(self):
		for assets in (None, ["source.zip"]):
			with self.assertRaises(frappe.ValidationError):
				self.set_rollout("v9.9.9", assets=assets)

	def call_report_pilot_update(self, version: str, error: str | None = None, token: str = "") -> None:
		set_request(
			method="POST",
			path="/api/method/central.api.pilot.report_pilot_update",
			headers={"X-Pilot-Token": token or self.token},
		)
		report_pilot_update(version=version, error=error)

	def test_a_failed_report_is_cleared_by_the_next_success(self):
		self.set_rollout("v2", percent=10)
		self.call_report_pilot_update("v1", "Pilot update failed: disk full")
		self.call_report_pilot_update("v2")
		credential = frappe.get_doc("Pilot Credential", "api-pilot-1")
		self.assertEqual((credential.pilot_version, credential.pilot_update_error), ("v2", None))

	def test_a_new_release_forgets_the_last_rollouts_failures(self):
		self.set_rollout("v2", percent=10)
		self.call_report_pilot_update("v1", "Pilot update failed: disk full")
		self.set_rollout("v3", percent=10)
		self.assertIsNone(frappe.db.get_value("Pilot Credential", "api-pilot-1", "pilot_update_error"))

	def test_asking_for_a_release_records_the_channel(self):
		self.set_rollout("v1", percent=10)
		self.call_pilot_release("late")
		self.assertEqual(
			frappe.db.get_value("Pilot Credential", "api-pilot-1", "pilot_update_channel"), "late"
		)

	def mock_rollout(self, servers: int = 100, percent: int = 30) -> list[str]:
		"""A v2 rollout to `percent` of `servers` fresh pilots, each other pilot revoked.
		Returns the tokens of the first group."""
		frappe.db.set_value("Pilot Credential", {"status": "Active"}, "status", "Revoked")
		self.set_rollout("v2", percent=percent)
		settings = frappe.get_single("Central Settings")
		tokens = {
			f"roll-{n}": PilotCredential.mint(team=self.team, pilot_credential_id=f"roll-{n}")
			for n in range(servers)
		}
		return [token for pilot, token in tokens.items() if settings.in_pilot_rollout_group(pilot, "normal")]

	def rollout_percent(self) -> int:
		return frappe.get_single("Central Settings").pilot_rollout_percent

	def test_95_percent_of_the_group_updated_releases_to_everyone(self):
		group = self.mock_rollout()
		needed = math.ceil(len(group) * 0.95)
		for token in group[needed:]:
			self.call_report_pilot_update("v1", "Pilot update failed: disk full", token)
		for token in group[: needed - 1]:
			self.call_report_pilot_update("v2", token=token)

		self.assertEqual(
			frappe.get_single("Central Settings").pilot_rollout_counts(),
			{"group": len(group), "updated": needed - 1, "failed": len(group) - needed},
		)
		self.assertEqual(self.rollout_percent(), 30)

		self.call_report_pilot_update("v2", token=group[needed - 1])
		self.assertEqual(self.rollout_percent(), 100)
		self.assertTrue(
			frappe.db.exists(
				"Comment",
				{"reference_doctype": "Central Settings", "content": ("like", "Released v2 to everyone%")},
			)
		)

	def test_no_auto_release_while_halted_or_turned_off(self):
		for field in ("pilot_rollout_halted", "pilot_auto_release_percent"):
			group = self.mock_rollout()
			frappe.db.set_single_value("Central Settings", field, 1 if field == "pilot_rollout_halted" else 0)
			for token in group:
				self.call_report_pilot_update("v2", token=token)
			self.assertEqual(self.rollout_percent(), 30)

	def test_late_pilots_never_count_toward_the_group(self):
		group = self.mock_rollout(servers=10, percent=50)
		frappe.db.set_value("Pilot Credential", {"status": "Active"}, "pilot_update_channel", "late")
		self.assertEqual(frappe.get_single("Central Settings").pilot_rollout_counts()["group"], 0)
		self.assertTrue(group)
