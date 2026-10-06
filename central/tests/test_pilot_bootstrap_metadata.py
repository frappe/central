import json
from unittest import TestCase
from unittest.mock import Mock, patch

from central.integrations.atlas import MAXIMUM_METADATA_VALUE_BYTES
from central.integrations.resource_actions import _create_payload

PILOT = "central.integrations.pilot"
TELEMETRY_CONFIG = {"endpoint": "https://datum.in-mumbai.example.test", "token": "datum-token"}


def pilot_request():
	request = Mock(team="TEAM-00001", region="in-mumbai", server_id="server-action-1")
	request.name = "action-1"
	request.get_configuration.return_value = Mock(
		image_id="image-1",
		virtual_cpu_count=2,
		memory_mib=4096,
		disk_mib=10240,
		hostname="pilot-1",
		ssh_keys=[],
		ssh_key_ids=[],
		image_tags={"purpose": "pilot"},
	)
	return request


class TestPilotBootstrapMetadata(TestCase):
	def setUp(self):
		self.enterContext(patch(f"{PILOT}.PilotCredential.mint", return_value="token"))
		self.enterContext(patch(f"{PILOT}.central_url", return_value="https://central.test"))
		self.enterContext(patch(f"{PILOT}.jwks_url", return_value="https://central.test/jwks"))

	def test_pilot_payload_contains_the_telemetry_configuration(self):
		request = pilot_request()
		with (
			patch(f"{PILOT}.get_telemetry_base_url", return_value=TELEMETRY_CONFIG["endpoint"]),
			patch(f"{PILOT}.region_id_of", return_value=7),
			patch(f"{PILOT}.mint_datum_token", return_value="datum-token") as mint,
		):
			payload = _create_payload(request)

		metadata = payload["metadata"]
		self.assertEqual(json.loads(metadata["pilot-common-config"]), {"telemetry": TELEMETRY_CONFIG})
		self.assertTrue(
			all(len(value.encode()) <= MAXIMUM_METADATA_VALUE_BYTES for value in metadata.values()),
			"Metal refuses a guest metadata value over 1 KiB.",
		)
		# The server does not exist yet, so the token names the one this request creates.
		mint.assert_called_once_with(7, "server-action-1")

	def test_a_region_without_a_telemetry_host_does_not_block_pilot_creation(self):
		request = pilot_request()
		with patch(f"{PILOT}.get_telemetry_base_url", return_value=None):
			payload = _create_payload(request)

		self.assertNotIn("pilot-common-config", payload["metadata"])
		request.record_diagnostic.assert_called_once()
