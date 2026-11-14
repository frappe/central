import re
import secrets

import frappe
from frappe import _

PARTNER_CODE_PREFIX_LENGTH = 3
PARTNER_CODE_DIGITS = 5
PARTNER_CODE_ATTEMPTS = 10


def generate_partner_code(team_name: str) -> str:
	"""A new partner code, such as `TRI-48213`: three letters of the team name and five
	random digits. The unique constraint on `Team.partner_code` is the final guard."""
	letters = re.sub(r"[^A-Za-z]", "", team_name).upper()
	prefix = letters[:PARTNER_CODE_PREFIX_LENGTH].ljust(PARTNER_CODE_PREFIX_LENGTH, "P")

	for _attempt in range(PARTNER_CODE_ATTEMPTS):
		digits = str(secrets.randbelow(10**PARTNER_CODE_DIGITS)).zfill(PARTNER_CODE_DIGITS)
		code = f"{prefix}-{digits}"
		if not frappe.db.exists("Team", {"partner_code": code}):
			return code

	frappe.throw(_("Could not generate a unique partner code. Try again."))


def get_partner_team(connect_partner_id: str) -> frappe._dict | None:
	"""The team that represents a Connect partner, with its partner code."""
	return frappe.db.get_value(
		"Team",
		{"connect_partner_id": connect_partner_id},
		["name", "partner_code"],
		as_dict=True,
	)
