# Copyright (c) 2026, frappe and Contributors
# See license.txt

import hashlib
import hmac
import json
from unittest.mock import patch

import frappe
import requests
from frappe.integrations.doctype.webhook.webhook import retry_failed_webhooks
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, now_datetime, set_request

from central.api.meta_webhook import handler
from central.integrations.oauth.meta import ROUTE, check_route, save_route
from central.integrations.oauth.meta_webhook import (
	CENTRAL_SIGNATURE_HEADER,
	WEBHOOK,
	deliver,
	ensure_meta_webhook,
)
from central.tests import test_email_oauth

APP_SECRET = "meta-secret"  # set by enable_meta
VERIFY_TOKEN = "meta-verify-token"
WABA_SECRET = "waba-webhook-secret"


def meta_event(*waba_ids: str) -> dict:
	return {
		"object": "whatsapp_business_account",
		"entry": [
			{
				"id": waba_id,
				"changes": [{"field": "messages", "value": {"messages": [{"id": f"m-{waba_id}"}]}}],
			}
			for waba_id in waba_ids
		],
	}


def hex_hmac(secret: str, body: bytes) -> str:
	return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def site_reply(status: int) -> requests.Response:
	response = requests.Response()
	response.status_code = status
	response._content = b"ok"
	response.url = "https://site.test"
	return response


class TestMetaWebhook(IntegrationTestCase):
	setUp_site = test_email_oauth.TestEmailOAuth.setUp
	enable_meta = test_email_oauth.TestEmailOAuth.enable_meta

	def setUp(self):
		self.setUp_site()
		self.enable_meta()
		ensure_meta_webhook()
		self.enterContext(patch.dict(frappe.local.conf, {"meta_webhook_verify_token": VERIFY_TOKEN}))
		self.waba_id = f"waba-{frappe.generate_hash(length=8)}"
		frappe.get_doc(
			{
				"doctype": ROUTE,
				"waba_id": self.waba_id,
				"team": self.team,
				"server": self.server,
				"site": self.site,
				"webhook_secret": WABA_SECRET,
			}
		).insert()

	def call_meta(self, body: dict, signature: str | None = None):
		"""POST as Meta; returns the response and the background jobs it queued."""
		raw = json.dumps(body).encode()
		signature = signature if signature is not None else f"sha256={hex_hmac(APP_SECRET, raw)}"
		set_request(
			method="POST",
			path="/api/method/central.api.meta_webhook.handler",
			data=raw,
			headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature},
		)
		with patch("frappe.enqueue") as enqueue:
			response = handler()
		return response, enqueue.call_args_list

	def subscribe(self, token: str):
		set_request(method="GET", path="/api/method/central.api.meta_webhook.handler")
		frappe.local.form_dict = frappe._dict(
			{"hub.mode": "subscribe", "hub.verify_token": token, "hub.challenge": "challenge-42"}
		)
		return handler()

	def logs(self) -> list:
		return frappe.get_all(
			"Webhook Request Log",
			{"webhook": WEBHOOK, "reference_document": self.site},
			["name", "status", "url", "headers", "attempt", "reference_doctype"],
		)

	def test_meta_subscribes_with_the_verify_token_only(self):
		response = self.subscribe(VERIFY_TOKEN)
		self.assertEqual((response.status_code, response.get_data(as_text=True)), (200, "challenge-42"))

		self.assertEqual(self.subscribe("wrong-token").status_code, 403)
		with patch.dict(frappe.local.conf, {"meta_webhook_verify_token": None}):
			self.assertEqual(self.subscribe("").status_code, 403)

	def test_a_body_without_meta_signature_is_refused_and_not_logged(self):
		for signature in ("", "sha256=" + hex_hmac("not-the-app-secret", b"{}"), "not-hex"):
			response, jobs = self.call_meta(meta_event(self.waba_id), signature=signature)
			self.assertEqual(response.status_code, 403)
			self.assertEqual(jobs, [])
		self.assertEqual(self.logs(), [])

	def test_only_routed_wabas_are_relayed_each_with_its_own_entries(self):
		response, jobs = self.call_meta(meta_event(self.waba_id, "waba-not-routed"))

		self.assertEqual(response.status_code, 200)
		self.assertEqual(len(jobs), 1)
		job = jobs[0].kwargs
		self.assertEqual(job["waba_id"], self.waba_id)
		self.assertEqual(job["queue"], "short")
		self.assertEqual([entry["id"] for entry in job["body"]["entry"]], [self.waba_id])

		_, jobs = self.call_meta(meta_event("waba-not-routed"))
		self.assertEqual(jobs, [])

	def test_delivery_is_signed_with_the_waba_secret_and_logged_delivered(self):
		with patch("requests.Session.request", return_value=site_reply(200)) as send:
			deliver(self.waba_id, meta_event(self.waba_id))

		sent = send.call_args.kwargs
		self.assertEqual(sent["url"], f"https://{self.site}/api/method/whatsapp.whatsapp.webhook.handler")
		# the site checks the header against the bytes it receives
		self.assertEqual(
			sent["headers"][CENTRAL_SIGNATURE_HEADER],
			f"sha256={hex_hmac(WABA_SECRET, sent['data'].encode())}",
		)
		(log,) = self.logs()
		self.assertEqual((log.status, log.reference_doctype), ("Delivered", "Site"))
		self.assertNotIn(WABA_SECRET, log.headers)

	def test_site_down_then_up_retry_job_delivers_the_same_signed_body(self):
		with patch("requests.Session.request", side_effect=requests.ConnectionError("site down")) as send:
			deliver(self.waba_id, meta_event(self.waba_id))
		first = send.call_args.kwargs
		(log,) = self.logs()
		self.assertEqual(log.status, "Failed")
		self.assertGreater(frappe.db.get_value("Webhook Request Log", log.name, "next_retry"), now_datetime())

		frappe.db.set_value(
			"Webhook Request Log", log.name, "next_retry", add_to_date(now_datetime(), minutes=-1)
		)
		with patch("requests.Session.request", return_value=site_reply(200)) as send:
			retry_failed_webhooks()
		(retry,) = [c.kwargs for c in send.call_args_list if c.kwargs["url"] == first["url"]]
		self.assertEqual(retry["data"], first["data"])
		self.assertEqual(
			retry["headers"][CENTRAL_SIGNATURE_HEADER], first["headers"][CENTRAL_SIGNATURE_HEADER]
		)
		(log,) = self.logs()
		self.assertEqual((log.status, log.attempt), ("Delivered", 2))

	def test_a_disconnected_waba_is_not_sent(self):
		frappe.delete_doc(ROUTE, self.waba_id)
		with patch("requests.Session.request") as send:
			deliver(self.waba_id, meta_event(self.waba_id))
		send.assert_not_called()
		self.assertEqual(self.logs(), [])

	def test_a_410_from_the_site_deletes_the_route_and_is_not_retried(self):
		with patch("requests.Session.request", return_value=site_reply(410)):
			deliver(self.waba_id, meta_event(self.waba_id))

		self.assertFalse(frappe.db.exists(ROUTE, self.waba_id))
		(log,) = self.logs()
		self.assertEqual(log.status, "Delivered")
		self.assertIsNone(frappe.db.get_value("Webhook Request Log", log.name, "next_retry"))

	def test_a_terminated_server_frees_its_wabas_for_another_site_of_the_team(self):
		server = frappe.get_doc("Virtual Machine", self.server)
		with patch("frappe.enqueue"):
			server.status = "Terminated"
			server.save()

		self.assertFalse(frappe.db.exists(ROUTE, self.waba_id))
		_, jobs = self.call_meta(meta_event(self.waba_id))
		self.assertEqual(jobs, [])

		other_server = frappe.get_doc(
			{
				"doctype": "Virtual Machine",
				"resource_id": f"vm-{frappe.generate_hash(length=6)}",
				"team": self.team,
				"region": server.region,
			}
		).insert()
		other_site = frappe.get_doc(
			{
				"doctype": "Site",
				"site_name": f"other-{self.site}",
				"team": self.team,
				"server": other_server.name,
			}
		).insert()
		check_route(self.waba_id, other_site.name)
		save_route(self.waba_id, self.team, other_server.name, other_site.name, WABA_SECRET)
		self.assertEqual(frappe.db.get_value(ROUTE, self.waba_id, "site"), other_site.name)

	def test_deleting_a_site_deletes_its_routes(self):
		frappe.delete_doc("Site", self.site)
		self.assertFalse(frappe.db.exists(ROUTE, self.waba_id))

	def test_seeded_webhook_is_on_site_with_five_retries_and_never_fires(self):
		webhook = frappe.get_doc("Webhook", WEBHOOK)
		self.assertEqual(
			(
				webhook.webhook_doctype,
				webhook.enabled,
				webhook.max_retries,
				webhook.condition,
				webhook.background_jobs_queue,
			),
			("Site", 1, 5, "False", "short"),
		)
