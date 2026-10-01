from __future__ import annotations

import frappe
from werkzeug.wrappers import Response

from central.central.doctype.central_sso_settings.central_sso_settings import CentralSSOSettings


def jwks_document() -> dict:
	"""Publish the initialized Pilot and Atlas public Ed25519 keys."""
	settings = CentralSSOSettings.instance()
	return {"keys": settings.get_jwks("pilot")["keys"] + settings.get_jwks("atlas")["keys"]}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_jwks() -> Response:
	response = Response(mimetype="application/json")
	response.data = frappe.as_json(jwks_document())
	return response
