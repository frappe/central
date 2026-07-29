from __future__ import annotations

import frappe
from werkzeug.wrappers import Response

from central.central.doctype.central_sso_settings.central_sso_settings import CentralSSOSettings

# Public discovery endpoint. A bench fetches this to learn Central's RSA public key(s) and
# verifies Central-minted tokens against them offline. Guest-readable by design — a public
# key is not a secret — and never triggers key generation (that stays on the authenticated
# signing path). Served as a RAW `{"keys": [...]}` document (not Frappe's `{"message": ...}`
# envelope) so a standard JWKS client — including the bench's PyJWKClient — can consume it.


def jwks_document() -> dict:
	"""The JSON Web Key Set of Central's active signing key(s): ``{"keys": [...]}``."""
	return CentralSSOSettings.instance().jwks()


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_jwks() -> Response:
	response = Response(mimetype="application/json")
	response.data = frappe.as_json(jwks_document())
	return response
