# Copyright (c) 2026, frappe and Contributors
# See license.txt

import hashlib
import random

import frappe
import jwt
from frappe.tests import IntegrationTestCase
from frappe.utils import set_request

from central.api.grove import datum_token
from central.central.doctype.central_sso_settings.central_sso_settings import CentralSSOSettings
from central.sso import DATUM_SCOPE, DATUM_TTL
from central.tests.utils import ensure_atlas_instance

TOKEN = "grove-token-1"


class TestGroveDatumToken(IntegrationTestCase):
	"""The token a Grove box pushes to its region's datum with: the X-Grove-Token whose hash AI
	Settings holds may mint one for a `grove:` resource in a region Central knows; nothing else may."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.region_id = random.randint(1, 65535)
		self.region = ensure_atlas_instance("grove-api-region", atlas_region_id=str(self.region_id))
		frappe.db.set_value("Region", self.region, "atlas_region_id", str(self.region_id))
		CentralSSOSettings.instance().initialize_signing_key("atlas")
		self.set_hash(hashlib.sha256(TOKEN.encode()).hexdigest())
		frappe.set_user("Guest")

	def set_hash(self, value):
		frappe.db.set_single_value("AI Settings", "grove_token_hash", value)

	def call(self, region, resource_id, token=TOKEN):
		"""Invoke the endpoint as Grove would: an X-Grove-Token header, or none."""
		headers = {"X-Grove-Token": token} if token is not None else {}
		set_request(method="GET", path="/api/method/central.api.grove.datum_token", headers=headers)
		return datum_token(region, resource_id)

	def claims(self, region, resource_id):
		answer = self.call(region, resource_id)
		self.assertEqual(DATUM_TTL, answer["expires_in"])
		return jwt.decode(answer["token"], options={"verify_signature": False})

	def test_groves_token_gets_a_write_token_for_its_box_in_its_region(self):
		claims = self.claims(self.region, "grove:mc-1")
		self.assertEqual("grove:mc-1", claims["resource_id"])
		self.assertEqual(["write"], claims["access"])
		self.assertEqual(DATUM_SCOPE, claims["scope"])
		self.assertEqual(f"atlas-datum:{self.region_id}", claims["aud"])

	def test_a_wrong_token_is_refused(self):
		with self.assertRaises(frappe.AuthenticationError):
			self.call(self.region, "grove:mc-1", token="not-it")

	def test_a_missing_header_is_refused(self):
		with self.assertRaises(frappe.AuthenticationError):
			self.call(self.region, "grove:mc-1", token=None)

	def test_a_blank_hash_admits_nobody(self):
		self.set_hash("")
		with self.assertRaises(frappe.AuthenticationError):
			self.call(self.region, "grove:mc-1")

	def test_a_resource_outside_groves_namespace_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.call(self.region, "vm-abc123")

	def test_a_region_central_does_not_know_is_refused(self):
		with self.assertRaises(frappe.DoesNotExistError):
			self.call("no-such-region", "grove:mc-1")
