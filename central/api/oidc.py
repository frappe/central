from __future__ import annotations

import json

import frappe
from frappe.oauth import generate_json_error_response
from oauthlib.oauth2 import FatalClientError, OAuth2Error
from oauthlib.openid.connect.core.endpoints.pre_configured import Server
from werkzeug.wrappers import Response

from central.central.doctype.central_sso_settings.central_sso_settings import CentralSSOSettings
from central.oidc import OIDCRequestValidator


@frappe.whitelist(allow_guest=True, methods=["POST"])
def get_token() -> None:
	"""Frappe's OAuth token endpoint, with RS256 ID tokens."""
	request = frappe.request
	headers = dict(request.headers)
	if authorization := getattr(frappe.local, "oidc_authorization", None):
		headers["Authorization"] = authorization

	server = Server(OIDCRequestValidator())
	try:
		_headers, body, _status = server.create_token_response(
			request.url, request.method, request.form, headers
		)
	except (FatalClientError, OAuth2Error) as error:
		return generate_json_error_response(error)

	frappe.local.response = frappe._dict(json.loads(body))
	if frappe.local.response.error:
		frappe.local.response["http_status_code"] = 400


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_jwks() -> Response:
	response = Response(mimetype="application/json")
	response.data = frappe.as_json(CentralSSOSettings.instance().get_jwks("oidc"))
	return response
