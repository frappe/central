from unittest.mock import MagicMock, patch

import frappe

from central.api.servers import create_server
from central.integrations.resource_actions import _process_locked

IMAGE = {
	"id": "pilot-test-image",
	"rootfs_size_mib": 8192,
	"tags": {"purpose": "pilot"},
}


def create_billed_server(team, region, plan, **overrides):
	"""Keep purchase policy and billing real while replacing regional HTTP calls."""
	client = MagicMock()
	client.tenant_id = frappe.db.get_value("Team", team, "tenant_id")
	client.create_vm.return_value = {"id": "vm-billing-test", "tenant_id": client.tenant_id}
	values = {
		"team": team,
		"region": region,
		"title": "web-1",
		"plan": plan,
		"offering": "pilot",
		"image_id": IMAGE["id"],
		"request_key": frappe.generate_hash(length=32),
		**overrides,
	}
	with (
		patch("central.resource_actions.selected_image", return_value=IMAGE),
		patch("central.integrations.resource_actions._client", return_value=client),
		patch(
			"central.integrations.pilot.central_url",
			return_value="https://central.example.test",
		),
		patch(
			"central.integrations.pilot.jwks_url",
			return_value="https://central.example.test/jwks",
		),
		patch("central.integrations.servers.observe_server", return_value="Running"),
		patch("frappe.enqueue"),
		patch("frappe.db.commit"),
	):
		result = create_server(**values)
		_process_locked(result["action"])
		action = frappe.get_doc("Resource Action", result["action"])
		return action, client
