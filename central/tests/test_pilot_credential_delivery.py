from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.central.doctype.asset.asset import Asset
from central.central.doctype.pilot_credential.pilot_credential import PilotCredential
from central.errors import AtlasResourceGone
from central.integrations.servers import observe_server
from central.tests.utils import ensure_atlas_instance


class TestPilotCredentialRevocation(IntegrationTestCase):
	def test_confirmed_absence_revokes_only_the_owning_server_credentials(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		team = frappe.get_doc(
			{"doctype": "Team", "team_name": "Credential", "owner_user": "Administrator"}
		).insert()
		ensure_atlas_instance("test-credentials")
		with patch.object(Asset, "ensure_subscription_enabled"):
			asset = frappe.get_doc(
				{
					"doctype": "Asset",
					"resource_id": "credential-" + frappe.generate_hash(length=8),
					"team": team.name,
					"atlas_vm_id": "vm-00001",
					"cluster": "test-credentials",
					"status": "Running",
				}
			).insert()
		credential_id = "credential-" + frappe.generate_hash(length=8)
		token = PilotCredential.mint(team.name, credential_id, asset=asset.name, audience_id=credential_id)
		other_id = "credential-" + frappe.generate_hash(length=8)
		other_token = PilotCredential.mint(team.name, other_id, audience_id=other_id)
		self.assertIsNotNone(PilotCredential.verify(token))
		with (
			patch("central.integrations.servers._client") as client,
			patch.object(Asset, "disable_active_subscription"),
		):
			client.return_value.get_vm.side_effect = AtlasResourceGone("gone")
			observe_server(asset)
		self.assertIsNone(PilotCredential.verify(token))
		self.assertIsNotNone(PilotCredential.verify(other_token))
