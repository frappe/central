"""Unit tests for the Atlas webhook gate (spec/16-central.md § The wire contract).
Covers headers, region resolution, disabled instances, the HMAC compare, and
stored-row re-verifiability. get_request_header is patched, no live HTTP."""

from __future__ import annotations

import hashlib
import hmac
import time
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.integrations import atlas as atlas_module
from central.integrations.atlas import _authenticate_atlas_webhook, signature_matches
from central.tests.utils import ensure_region

REGION = "blr-sig"
SECRET = "whs_test_secret"
BODY = b'{"type":"vm.created","payload":{"name":"vm-1"}}'

# --- Golden vector: pinned wire contract, mirrored in atlas/tests/test_central.py ---
# Nothing binds the two repos: a format change made on ONE side leaves both suites green
# while every real delivery fails. Do not regenerate the digest to make a test pass.
GOLDEN_SECRET = "atlas-golden-secret"
GOLDEN_TIMESTAMP = "2026-06-18 10:00:00.000000"
GOLDEN_BODY = (
	b'{"event_id": "evt-golden-1", "type": "vm.created", '
	b'"payload": {"name": "vm-golden"}, "occurred_at": "2026-06-18 10:00:00"}'
)
GOLDEN_SIGNATURE = "918bd05acd9cb434d5e2b78bb7ebc977d6c8abefa979687d6575c375ea9370c5"


def _sign(body: bytes, timestamp: str, secret: str = SECRET) -> str:
	return hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


@contextmanager
def _headers(region=REGION, timestamp=None, signature=None, body=BODY, secret=SECRET):
	"""Patch get_request_header with the given trio, signing validly by default."""
	ts = timestamp if timestamp is not None else str(int(time.time()))
	sig = signature if signature is not None else _sign(body, ts, secret)
	values = {"X-Atlas-Region": region, "X-Atlas-Timestamp": ts, "X-Atlas-Signature": sig}
	with patch.object(atlas_module.frappe, "get_request_header", side_effect=lambda k: values.get(k)):
		yield


class TestGoldenVector(unittest.TestCase):
	"""Pin Central's verifier to the wire contract, independently of any request
	plumbing. Atlas asserts the same constants against its signer."""

	def test_verifier_accepts_the_golden_signature(self) -> None:
		self.assertTrue(signature_matches(GOLDEN_SECRET, GOLDEN_TIMESTAMP, GOLDEN_BODY, GOLDEN_SIGNATURE))

	def test_golden_signature_covers_the_timestamp(self) -> None:
		# The timestamp is inside the signed string, not merely alongside it, so it
		# can't be swapped for a fresh one without the secret.
		self.assertFalse(
			signature_matches(GOLDEN_SECRET, "2026-06-18 10:00:01.000000", GOLDEN_BODY, GOLDEN_SIGNATURE)
		)

	def test_golden_signature_covers_every_body_byte(self) -> None:
		self.assertFalse(
			signature_matches(GOLDEN_SECRET, GOLDEN_TIMESTAMP, GOLDEN_BODY + b" ", GOLDEN_SIGNATURE)
		)


class TestVerifyAtlasSignature(IntegrationTestCase):
	def setUp(self) -> None:
		ensure_region(REGION)
		if frappe.db.exists("Atlas Instance", REGION):
			frappe.delete_doc("Atlas Instance", REGION, force=True, ignore_permissions=True)
		self.instance = frappe.get_doc(
			{
				"doctype": "Atlas Instance",
				"region": REGION,
				"base_url": "https://blr.atlas.example.test",
				"status": "Active",
				"api_key": "admin_key",
				"api_secret": "admin_secret",
			}
		).insert(ignore_permissions=True)
		frappe.utils.password.set_encrypted_password(
			"Atlas Instance", self.instance.name, SECRET, "webhook_secret"
		)

	def tearDown(self) -> None:
		frappe.delete_doc("Atlas Instance", REGION, force=True, ignore_permissions=True)

	# ----- happy path --------------------------------------------------------

	def test_valid_signature_returns_the_region(self) -> None:
		with _headers():
			self.assertEqual(_authenticate_atlas_webhook(BODY).cluster, REGION)

	# ----- missing headers: identical rejection every way --------------------

	def test_missing_headers_are_all_rejected_identically(self) -> None:
		messages = set()
		for missing in ("X-Atlas-Region", "X-Atlas-Timestamp", "X-Atlas-Signature"):
			ts = str(int(time.time()))
			values = {
				"X-Atlas-Region": REGION,
				"X-Atlas-Timestamp": ts,
				"X-Atlas-Signature": _sign(BODY, ts),
			}
			values[missing] = None
			with patch.object(
				atlas_module.frappe, "get_request_header", side_effect=lambda k, values=values: values.get(k)
			):
				with self.assertRaises(frappe.PermissionError) as ctx:
					_authenticate_atlas_webhook(BODY)
			messages.add(str(ctx.exception))
		# Same wording regardless of which header was missing — no detail leaked.
		self.assertEqual(len(messages), 1)

	# ----- timestamp ----------------------------------------------------------

	def test_unparseable_timestamp_is_rejected(self) -> None:
		with _headers(timestamp="not-a-number", signature="irrelevant"):
			with self.assertRaises(frappe.PermissionError):
				_authenticate_atlas_webhook(BODY)

	# ----- region / instance resolution ---------------------------------------

	def test_unknown_region_is_rejected(self) -> None:
		ts = str(int(time.time()))
		with _headers(region="no-such-region", timestamp=ts, signature=_sign(BODY, ts)):
			with self.assertRaises(frappe.PermissionError):
				_authenticate_atlas_webhook(BODY)

	def test_disabled_instance_is_rejected(self) -> None:
		self.instance.db_set("status", "Disabled")
		with _headers():
			with self.assertRaises(frappe.PermissionError):
				_authenticate_atlas_webhook(BODY)

	def test_instance_with_no_webhook_secret_is_rejected(self) -> None:
		# A not-yet-rotated instance (Phase 2 of rollout not complete for it yet).
		frappe.utils.password.set_encrypted_password(
			"Atlas Instance", self.instance.name, "", "webhook_secret"
		)
		with _headers():
			with self.assertRaises(frappe.PermissionError):
				_authenticate_atlas_webhook(BODY)

	# ----- the actual HMAC comparison ------------------------------------------

	def test_wrong_secret_is_rejected(self) -> None:
		ts = str(int(time.time()))
		with _headers(timestamp=ts, signature=_sign(BODY, ts, secret="not-the-real-secret")):
			with self.assertRaises(frappe.PermissionError):
				_authenticate_atlas_webhook(BODY)

	def test_tampered_body_is_rejected(self) -> None:
		# Signature computed over the original body, but a different body arrives.
		with _headers():
			with self.assertRaises(frappe.PermissionError):
				_authenticate_atlas_webhook(BODY + b"tampered")

	def test_signature_over_reparsed_json_does_not_verify(self) -> None:
		"""Regression for the raw-bytes requirement: re-serializing the same JSON
		content (e.g. via json.dumps after frappe.parse_json) is not guaranteed to
		produce byte-identical output — a signature computed over that reserialized
		form must NOT verify against the original raw bytes."""
		import json

		reparsed = json.dumps(frappe.parse_json(BODY.decode()), sort_keys=True).encode()
		self.assertNotEqual(reparsed, BODY)  # sanity: they really do differ
		ts = str(int(time.time()))
		with _headers(timestamp=ts, signature=_sign(reparsed, ts)):
			with self.assertRaises(frappe.PermissionError):
				_authenticate_atlas_webhook(BODY)


class TestEventEndpointSignatureGate(IntegrationTestCase):
	"""End-to-end through the whitelisted event() API: a well-formed signed POST
	is accepted and produces the same ingest_event behavior as before; a badly
	signed one is rejected before ingest_event (or any DB write) ever runs."""

	def setUp(self) -> None:
		ensure_region(REGION)
		if frappe.db.exists("Atlas Instance", REGION):
			frappe.delete_doc("Atlas Instance", REGION, force=True, ignore_permissions=True)
		self.instance = frappe.get_doc(
			{
				"doctype": "Atlas Instance",
				"region": REGION,
				"base_url": "https://blr.atlas.example.test",
				"status": "Active",
				"api_key": "admin_key",
				"api_secret": "admin_secret",
			}
		).insert(ignore_permissions=True)
		frappe.utils.password.set_encrypted_password(
			"Atlas Instance", self.instance.name, SECRET, "webhook_secret"
		)
		frappe.db.delete("Atlas Event", {"cluster": REGION})

	def tearDown(self) -> None:
		frappe.db.delete("Atlas Event", {"cluster": REGION})
		frappe.delete_doc("Atlas Instance", REGION, force=True, ignore_permissions=True)

	def _post(self, body: bytes, region=REGION, timestamp=None, signature=None):
		from central.api import atlas as atlas_api

		ts = timestamp if timestamp is not None else str(int(time.time()))
		sig = signature if signature is not None else _sign(body, ts)
		values = {"X-Atlas-Region": region, "X-Atlas-Timestamp": ts, "X-Atlas-Signature": sig}
		request = type("Request", (), {"get_data": staticmethod(lambda: body)})()
		with (
			patch.object(atlas_api.frappe, "request", request),
			# atlas_api.frappe and atlas_module.frappe are the same module object —
			# patching either patches frappe.get_request_header globally.
			patch.object(atlas_module.frappe, "get_request_header", side_effect=lambda k: values.get(k)),
		):
			return atlas_api.event()

	def test_valid_signed_post_is_ingested(self) -> None:
		body = frappe.as_json(
			{
				"type": "vm.rebooted",
				"payload": {"name": "vm-e2e"},
				"occurred_at": None,
				"event_id": "evt-e2e-1",
			}
		).encode()
		with patch("frappe.enqueue") as enqueue:
			result = self._post(body)
		# vm.rebooted isn't a known handler: recorded Ignored for the audit trail, never queued.
		self.assertEqual(result, {"ok": True, "queued": False})
		enqueue.assert_not_called()
		self.assertEqual(
			frappe.db.get_value("Atlas Event", {"event_id": "evt-e2e-1"}, "status"), "Ignored"
		)

	def test_badly_signed_post_is_rejected_before_any_write(self) -> None:
		# The gate throws rather than returning a body: the decorator runs before the
		# handler, so there is no path on which a bad signature reaches it.
		body = frappe.as_json(
			{
				"type": "vm.created",
				"payload": {"name": "vm-e2e-bad"},
				"occurred_at": None,
				"event_id": "evt-e2e-2",
			}
		).encode()
		# PermissionError is the assertion that matters: Frappe's handler turns it into
		# a 403 on the wire (confirmed against a live server), and it is raised before
		# the handler body, so nothing is written.
		with patch("frappe.enqueue") as enqueue:
			with self.assertRaises(frappe.PermissionError):
				self._post(body, signature="0" * 64)
		enqueue.assert_not_called()
		self.assertFalse(frappe.db.exists("Atlas Event", {"event_id": "evt-e2e-2"}))

	def test_non_ascii_signature_is_rejected_not_crashed(self) -> None:
		"""hmac.compare_digest raises TypeError on a non-ASCII str, and the header is
		attacker-controlled — comparing as bytes keeps it on the uniform 400 path
		instead of escaping the gate as a 500."""
		body = frappe.as_json({"type": "vm.created", "payload": {}, "event_id": "evt-e2e-3"}).encode()
		with self.assertRaises(frappe.PermissionError):
			self._post(body, signature="ü" * 64)

	def test_stored_row_is_re_verifiable(self) -> None:
		"""The reason raw_body and signature are columns: the row can be proved to be
		what Atlas sent, not just what Central recorded."""
		body = frappe.as_json(
			{
				"type": "vm.created",
				"payload": {"name": "vm-e2e-ok"},
				"occurred_at": None,
				"event_id": "evt-e2e-4",
			}
		).encode()
		with patch("frappe.enqueue"):
			self._post(body)

		event = frappe.get_doc("Atlas Event", {"event_id": "evt-e2e-4"})
		self.assertEqual(event.raw_body.encode(), body)  # byte-for-byte, not reserialized
		self.assertTrue(event.verify_signature())

		# A row whose stored bytes were edited after the fact no longer verifies.
		event.db_set("raw_body", event.raw_body.replace("vm-e2e-ok", "vm-tampered"))
		self.assertFalse(frappe.get_doc("Atlas Event", event.name).verify_signature())
