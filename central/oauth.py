from __future__ import annotations

import json
from urllib.parse import urljoin

import frappe
import frappe.oauth as frappe_oauth
from oauthlib.oauth2 import FatalClientError, OAuth2Error

from central.iam import get_fc_teams_claim


def _add_fc_teams_to_userinfo(userinfo: dict, user: str | None = None) -> dict:
	if not user:
		user = userinfo.get("email")

	userinfo["fc_teams"] = get_fc_teams_claim(user) if user else {}
	return userinfo


def _get_userinfo_without_request(user) -> dict:
	picture = None
	frappe_server_url = frappe.utils.get_url()
	valid_url_schemes = ("http", "https", "ftp", "ftps")

	if user.user_image:
		if frappe.utils.validate_url(user.user_image, valid_schemes=valid_url_schemes):
			picture = user.user_image
		else:
			picture = urljoin(frappe_server_url, user.user_image)

	return frappe._dict(
		{
			"sub": frappe.db.get_value(
				"User Social Login",
				{"parent": user.name, "provider": "frappe"},
				"userid",
			),
			"name": " ".join(filter(None, [user.first_name, user.last_name])),
			"given_name": user.first_name,
			"family_name": user.last_name,
			"email": user.email,
			"picture": picture,
			"roles": frappe.get_roles(user.name),
			"iss": frappe_server_url,
		}
	)


def install_oauth_claim_patch() -> None:
	"""Patch Frappe's OpenID userinfo generator until a first-class claim hook exists."""
	if getattr(frappe_oauth, "_central_fc_teams_patched", False):
		return

	base_get_userinfo = frappe_oauth.get_userinfo

	def get_userinfo_with_fc_teams(user):
		try:
			userinfo = base_get_userinfo(user)
		except RuntimeError as exc:
			if "object is not bound" not in str(exc):
				raise
			userinfo = _get_userinfo_without_request(user)
		return _add_fc_teams_to_userinfo(userinfo, user.name)

	frappe_oauth.get_userinfo = get_userinfo_with_fc_teams
	frappe_oauth._central_fc_teams_patched = True


@frappe.whitelist()
def openid_profile(*args, **kwargs):
	install_oauth_claim_patch()

	from frappe.integrations.oauth2 import get_oauth_server
	from frappe.oauth import generate_json_error_response

	try:
		r = frappe.request
		_headers, body, _status = get_oauth_server().create_userinfo_response(
			r.url,
			headers=r.headers,
			body=r.form,
		)
		body = frappe._dict(json.loads(body))
		if not body.get("error"):
			_add_fc_teams_to_userinfo(body)
		frappe.local.response = body
		return

	except (FatalClientError, OAuth2Error) as e:
		return generate_json_error_response(e)
