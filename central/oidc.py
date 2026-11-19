from __future__ import annotations

import hmac
import json
from urllib.parse import unquote_plus

import frappe
import jwt
from frappe.integrations.oauth2 import ENDPOINTS
from frappe.oauth import OAuthWebRequestValidator, get_url_delimiter, get_userinfo
from frappe.website.page_renderers.base_renderer import BaseRenderer
from werkzeug import Response
from werkzeug.datastructures import Authorization

from central.central.doctype.central_sso_settings.central_sso_settings import (
	OIDC_ALGORITHM,
	CentralSSOSettings,
)
from central.sso import central_url

# Frappe serves /.well-known/openid-configuration itself, so this issuer lives under a sub-path.
ISSUER_PATH = "oidc"
DISCOVERY_PATH = f"{ISSUER_PATH}/.well-known/openid-configuration"
TOKEN_PATH = "/api/method/central.api.oidc.get_token"
JWKS_PATH = "/api/method/central.api.oidc.get_jwks"
# OpenID Connect gives each claim with its scope. Warpgate maps admins from `roles` and asks only for
# the standard scopes, so `roles` comes with `profile`.
SCOPE_CLAIMS = {
	"email": ("email",),
	"profile": ("name", "given_name", "family_name", "picture", "roles"),
}


class DiscoveryPage(BaseRenderer):
	"""Serves the OpenID Connect discovery document of the Central issuer."""

	def can_render(self) -> bool:
		return self.path == DISCOVERY_PATH

	def render(self) -> Response:
		return Response(json.dumps(get_openid_configuration()), mimetype="application/json")


def get_issuer() -> str:
	return f"{central_url()}/{ISSUER_PATH}"


def get_openid_configuration() -> dict:
	server_url = central_url()
	return {
		"issuer": get_issuer(),
		"authorization_endpoint": f"{server_url}{ENDPOINTS['authorization_endpoint']}",
		"token_endpoint": f"{server_url}{TOKEN_PATH}",
		"userinfo_endpoint": f"{server_url}{ENDPOINTS['userinfo_endpoint']}",
		"jwks_uri": f"{server_url}{JWKS_PATH}",
		"response_types_supported": ["code"],
		"subject_types_supported": ["public"],
		"id_token_signing_alg_values_supported": [OIDC_ALGORITHM],
		"token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
	}


def take_client_credentials() -> None:
	"""Keep Basic client credentials from Frappe's API key check. The token endpoint checks them."""
	if frappe.request.path.rstrip("/") == TOKEN_PATH:
		frappe.local.oidc_authorization = frappe.request.environ.pop("HTTP_AUTHORIZATION", None)


class OIDCRequestValidator(OAuthWebRequestValidator):
	"""Frappe's OAuth validator with RS256 ID tokens and a client secret check."""

	def authenticate_client(self, request, *args, **kwargs) -> bool:
		# Frappe loads the client without checking its secret.
		client_id, client_secret = _get_client_credentials(request)
		if not client_id or not client_secret:
			return False

		stored_secret = frappe.db.get_value("OAuth Client", client_id, "client_secret")
		if not stored_secret or not hmac.compare_digest(client_secret.encode(), stored_secret.encode()):
			return False

		request.client = frappe.get_cached_doc("OAuth Client", client_id).as_dict()

		return True

	def get_authorization_code_scopes(self, client_id, code, redirect_uri, request) -> list[str]:
		# OAuthlib picks the OpenID grant from these scopes before it validates the code. Frappe reads them
		# by client_id, which client_secret_basic does not send in the body, so no ID token would follow.
		scopes = frappe.db.get_value("OAuth Authorization Code", code, "scopes")
		return scopes.split(get_url_delimiter()) if scopes else []

	def finalize_id_token(self, id_token, token, token_handler, request) -> str:
		if request.nonce:
			id_token["nonce"] = request.nonce

		id_token["exp"] = id_token["iat"] + token["expires_in"]
		userinfo = get_userinfo(frappe.get_doc("User", request.user))
		for scope, claims in SCOPE_CLAIMS.items():
			if scope in request.scopes:
				id_token.update({claim: userinfo[claim] for claim in claims})

		# Frappe gives Administrator no OIDC user ID. The user name is stable and unique.
		id_token["sub"] = userinfo.sub or request.user
		id_token["iss"] = get_issuer()

		private_key, key_id = CentralSSOSettings.instance().get_signing_key("oidc")

		return jwt.encode(id_token, private_key, algorithm=OIDC_ALGORITHM, headers={"kid": key_id})


def _get_client_credentials(request) -> tuple[str | None, str | None]:
	"""Read client_secret_basic, else client_secret_post, credentials."""
	authorization = Authorization.from_header(request.headers.get("Authorization"))
	if authorization and authorization.type == "basic":
		# RFC 6749 section 2.3.1 form-encodes both values before base64.
		return unquote_plus(authorization.username), unquote_plus(authorization.password)

	return request.client_id, request.client_secret
