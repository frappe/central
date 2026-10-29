import json
from unittest.mock import Mock, patch

import frappe
from frappe.tests import IntegrationTestCase

from central.integrations.atlas import MAXIMUM_METADATA_BYTES
from central.integrations.pilot import METADATA_VALUE_BYTES
from central.integrations.resource_actions import _create_payload
from central.tests.test_iam import ensure_user

PILOT = "central.integrations.pilot"
TELEMETRY_CONFIG = {"endpoint": "https://datum.in-mumbai.example.test", "token": "datum-token"}
COMMON_SITE_CONFIG = (
	"central.central.doctype.central_settings.central_settings.CentralSettings.get_common_site_config"
)
MAIL_CONFIG = {
	"mail_server": "mail.c3.frappemail.com",
	"mail_port": 587,
	"use_ssl": 0,
	"use_tls": 1,
	"mail_login": "notifications-0123456789ab@c3.frappemail.com",
	"mail_password": "x" * 32,
	"auto_email_id": "notifications-0123456789ab@c3.frappemail.com",
	"always_use_account_email_id_as_sender": 1,
}
TRIAL_KEY_CONFIG = {
	"ai_keys": [
		{
			"name": "0123456789",
			"title": None,
			"geography": "ap-south-1",
			"gateway_url": "https://gw1.ap-south-1.llm.frappe.cloud",
			"api_key": "gr_" + "x" * 48,
		}
	]
}


def pilot_request(is_free_trial: int = 0):
	request = Mock(
		team="TEAM-00001",
		region="in-mumbai",
		server_id="server-action-1",
		requested_by=None,
		is_free_trial=is_free_trial,
	)
	request.name = "action-1"
	request.get_configuration.return_value = Mock(
		image_id="image-1",
		cpu_millicores=2000,
		memory_mib=4096,
		disk_mib=10240,
		hostname="pilot-1",
		ssh_keys=[],
		ssh_key_ids=[],
		user_data="",
		image_tags={"purpose": "pilot"},
	)
	return request


class TestPilotBootstrapMetadata(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		self.enterContext(patch(f"{PILOT}.PilotCredential.mint", return_value="token"))
		self.enterContext(patch(f"{PILOT}.central_url", return_value="https://central.test"))
		self.enterContext(patch(f"{PILOT}.jwks_url", return_value="https://central.test/jwks"))
		self.enterContext(patch(f"{PILOT}.jwks_document", return_value={"keys": [{"kid": "pilot-key"}]}))

	def test_pilot_payload_contains_the_telemetry_configuration(self):
		request = pilot_request()
		request.requested_by = ensure_user("certificate.customer@example.test")
		with (
			patch(f"{PILOT}.get_telemetry_base_url", return_value=TELEMETRY_CONFIG["endpoint"]),
			patch(f"{PILOT}.region_id_of", return_value=7),
			patch(f"{PILOT}.mint_datum_token", return_value="datum-token") as mint,
		):
			payload = _create_payload(request)

		metadata = payload["metadata"]
		self.assertEqual(
			json.loads(metadata["pilot-common-config"]),
			{"telemetry": TELEMETRY_CONFIG, "letsencrypt": {"email": request.requested_by}},
		)
		self.assertLessEqual(len(json.dumps(metadata).encode()), MAXIMUM_METADATA_BYTES)
		# The server does not exist yet, so the token names the one this request creates.
		mint.assert_called_once_with(7, "server-action-1")

	def test_a_region_without_a_telemetry_host_does_not_block_pilot_creation(self):
		request = pilot_request()
		with patch(f"{PILOT}.get_telemetry_base_url", return_value=None):
			payload = _create_payload(request)

		self.assertNotIn("pilot-common-config", payload["metadata"])
		request.record_diagnostic.assert_called_once()

	def test_customer_email_reaches_pilot_even_when_telemetry_is_unavailable(self):
		request = pilot_request()
		request.requested_by = ensure_user("certificate.customer@example.test")
		with patch(f"{PILOT}.get_telemetry_base_url", return_value=None):
			metadata = _create_payload(request)["metadata"]

		self.assertEqual(
			json.loads(metadata["pilot-common-config"]),
			{"letsencrypt": {"email": request.requested_by}},
		)
		request.record_diagnostic.assert_called_once()

	def test_every_server_gets_the_common_site_config_and_its_team(self):
		relay = {"raven_push_notification_server_url": "https://relay.example.test"}
		with (
			patch(f"{PILOT}.get_telemetry_base_url", return_value=None),
			patch(
				"central.central.doctype.central_settings.central_settings.CentralSettings.get_common_site_config",
				return_value=relay,
			),
		):
			metadata = _create_payload(pilot_request())["metadata"]

		self.assertEqual(json.loads(metadata["pilot-common-site-config"]), relay | {"fc_team": "TEAM-00001"})

	def test_the_server_mailbox_joins_the_common_site_config(self):
		relay = {"raven_push_notification_server_url": "https://relay.example.test"}
		mailbox = Mock()
		mailbox.get_site_config.return_value = {"mail_server": "smtp.example.test", "mail_port": 587}
		with (
			patch(f"{PILOT}.get_telemetry_base_url", return_value=None),
			patch(
				"central.central.doctype.central_settings.central_settings.CentralSettings.get_common_site_config",
				return_value=relay,
			),
			patch(f"{PILOT}.UserMailAccount.assign", return_value=mailbox),
		):
			metadata = _create_payload(pilot_request())["metadata"]

		self.assertEqual(
			json.loads(metadata["pilot-common-site-config"]),
			relay | {"fc_team": "TEAM-00001", "mail_server": "smtp.example.test", "mail_port": 587},
		)

	def test_a_free_trial_boots_with_a_pool_key_and_the_config_fits_metals_value_cap(self):
		relay = {"raven_push_notification_server_url": "https://relay.example.test"}
		mailbox, trial_key = Mock(), Mock()
		mailbox.get_site_config.return_value = MAIL_CONFIG
		trial_key.get_site_config.return_value = TRIAL_KEY_CONFIG
		with (
			patch(f"{PILOT}.get_telemetry_base_url", return_value=None),
			patch(COMMON_SITE_CONFIG, return_value=relay),
			patch(f"{PILOT}.UserMailAccount.assign", return_value=mailbox),
			patch(f"{PILOT}.AITrialKey.assign", return_value=trial_key) as assign,
		):
			metadata = _create_payload(pilot_request(is_free_trial=1))["metadata"]

		config = metadata["pilot-common-site-config"]
		self.assertEqual(
			json.loads(config), relay | {"fc_team": "TEAM-00001"} | MAIL_CONFIG | TRIAL_KEY_CONFIG
		)
		self.assertLessEqual(len(config.encode()), METADATA_VALUE_BYTES)
		self.assertTrue(assign.call_args.args[0].is_free_trial)

	def test_a_paid_creation_gets_no_trial_key(self):
		with patch(f"{PILOT}.get_telemetry_base_url", return_value=None):
			metadata = _create_payload(pilot_request())["metadata"]

		self.assertNotIn("ai_keys", json.loads(metadata["pilot-common-site-config"]))
