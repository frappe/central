import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils.password import get_decrypted_password, set_encrypted_password

from central.patches.v0_0.rename_sso_rsa_fields import DOCTYPE, FIELD_RENAMES, execute


class TestSSOKeyMigration(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.db.rollback)
		fields = [*FIELD_RENAMES, *FIELD_RENAMES.values()]
		frappe.db.delete("Singles", {"doctype": DOCTYPE, "field": ("in", fields)})
		frappe.db.delete("__Auth", {"doctype": DOCTYPE, "name": DOCTYPE, "fieldname": ("in", fields)})

	def seed_source(self):
		frappe.db.set_single_value(DOCTYPE, {"kid": "saved-id", "public_key": "saved-public-key"})
		set_encrypted_password(DOCTYPE, DOCTYPE, "test-private-key", "private_key")

	def test_migration_preserves_values_and_ciphertext_and_can_repeat(self):
		self.seed_source()
		ciphertext = self.get_ciphertext("private_key")

		execute()
		execute()

		values = frappe.db.get_singles_dict(DOCTYPE)
		self.assertEqual(values.rsa_key_id, "saved-id")
		self.assertEqual(values.rsa_public_key, "saved-public-key")
		self.assertEqual(get_decrypted_password(DOCTYPE, DOCTYPE, "rsa_private_key"), "test-private-key")
		self.assertEqual(self.get_ciphertext("rsa_private_key"), ciphertext)
		self.assertIsNone(self.get_ciphertext("private_key"))
		self.assertFalse(set(FIELD_RENAMES).intersection(values))

	def test_fresh_settings_do_not_generate_keys(self):
		execute()

		values = frappe.db.get_singles_dict(DOCTYPE)
		self.assertFalse(set(FIELD_RENAMES.values()).intersection(values))
		self.assertIsNone(self.get_ciphertext("rsa_private_key"))

	def test_existing_explicit_fields_are_untouched(self):
		frappe.db.set_single_value(DOCTYPE, "rsa_key_id", "existing-id")
		set_encrypted_password(DOCTYPE, DOCTYPE, "existing-test-key", "rsa_private_key")

		execute()

		self.assertEqual(frappe.db.get_singles_dict(DOCTYPE).rsa_key_id, "existing-id")
		self.assertEqual(get_decrypted_password(DOCTYPE, DOCTYPE, "rsa_private_key"), "existing-test-key")

	def test_conflicting_fields_fail_before_any_rename(self):
		self.seed_source()
		set_encrypted_password(DOCTYPE, DOCTYPE, "conflicting-test-key", "rsa_private_key")

		with self.assertRaises(frappe.ValidationError):
			execute()

		self.assertEqual(frappe.db.get_singles_dict(DOCTYPE).kid, "saved-id")
		self.assertEqual(get_decrypted_password(DOCTYPE, DOCTYPE, "private_key"), "test-private-key")

	def get_ciphertext(self, fieldname: str) -> str | None:
		rows = frappe.qb.get_query(
			"__Auth",
			filters={"doctype": DOCTYPE, "name": DOCTYPE, "fieldname": fieldname},
			fields=["password"],
		).run(pluck=True)
		return rows[0] if rows else None
