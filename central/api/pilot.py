from __future__ import annotations

import functools
from collections.abc import Callable

import frappe
from frappe import _

from central.central.doctype.pilot_credential.pilot_credential import PilotCredential

# The pilot→Central surface. The pilot (the on-VM agent, ~/pilot) authenticates with
# the opaque token Central minted for it (stored in the bench's bench.toml).
# The token rides an X-Pilot-Token header, NOT Authorization: Frappe's validate_auth()
# claims the Authorization header and 401s any scheme it can't map to a real user,
# before an allow_guest endpoint runs. The decorator resolves the token to its Pilot
# Credential and exposes it on frappe.local so handlers know who they serve.

TOKEN_HEADER = "X-Pilot-Token"


def pilot_credential_auth(func: Callable) -> Callable:
	"""Authenticate a pilot by its X-Pilot-Token. Exposes the resolved credential on
	frappe.local.pilot_credential; rejects a missing/unknown/revoked/expired token with
	401. Sits under @frappe.whitelist(allow_guest=True)."""

	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		credential = PilotCredential.verify(frappe.get_request_header(TOKEN_HEADER) or "")
		if not credential:
			frappe.throw(_("Invalid or expired pilot credential."), frappe.AuthenticationError)
		frappe.local.pilot_credential = credential
		return func(*args, **kwargs)

	return wrapper


@frappe.whitelist(allow_guest=True, methods=["GET"])
@pilot_credential_auth
def heartbeat() -> dict:
	"""Liveness + identity probe: proves a pilot can reach and authenticate to Central,
	and reports which team/pilot Central resolved it to."""
	credential = frappe.local.pilot_credential

	return {
		"ok": True,
		"team": credential.team,
		"pilot_credential_id": credential.pilot_credential_id,
		"server_time": frappe.utils.now(),
	}
