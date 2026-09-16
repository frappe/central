from __future__ import annotations

import frappe
from werkzeug.wrappers import Response

from central.central.doctype.central_sso_settings.central_sso_settings import CentralSSOSettings


def jwks_document() -> dict:
	"""The JSON Web Key Set of Central's active signing key(s): ``{"keys": [...]}``."""
	return CentralSSOSettings.instance().jwks()


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_jwks() -> Response:
	response = Response(mimetype="application/json")
	response.data = frappe.as_json(jwks_document())
	return response


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_atlas_jwks() -> Response:
	"""Serve the public Ed25519 keys accepted by the regional Atlas verifier."""
	document = CentralSSOSettings.instance().atlas_jwks()

	# Verifiers expect the raw JWKS document, without the Framework response envelope.
	return Response(frappe.as_json(document), mimetype="application/json")
