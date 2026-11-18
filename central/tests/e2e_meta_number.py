from unittest.mock import Mock, patch

import frappe

from central.billing.tests.e2e import _enter_test_mode
from central.integrations.oauth import meta
from central.tests.test_meta_signin import fake_graph


@frappe.whitelist(allow_guest=True, methods=["POST"])
def connect_with_fake_meta() -> dict:
	"""Test-only, gated on `allow_tests`: connect a new WABA against a fake Graph API and return
	the number fields the site gets. No route is saved and no secret is returned."""
	_enter_test_mode()

	waba_id = f"waba-e2e-{frappe.generate_hash(length=8)}"
	config = Mock(client_id="meta-app-id", get_password=Mock(return_value="meta-secret"))
	with (
		patch.object(meta, "get_provider", return_value=config),
		patch.object(meta.requests, "request", side_effect=fake_graph(waba_id)),
		patch.object(meta, "check_route"),
		patch.object(meta, "save_route"),
	):
		result = meta.connect_whatsapp("meta-token", "team-e2e", None, "e2e.localhost")
	return {key: result[key] for key in ("display_phone_number", "verified_name")}
