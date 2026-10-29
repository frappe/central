"""Seed an Email OAuth Provider record for each provider Frappe Cloud can sign mailboxes in with."""

import frappe

from central.integrations.email_oauth.email_oauth import PROVIDER

# Seeded disabled and without credentials; an operator adds the app's ID and secret and enables it
DEFAULT_PROVIDERS = {
	"microsoft": {
		"authorize_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
		"token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
		"scopes": [
			"offline_access",
			"https://outlook.office.com/IMAP.AccessAsUser.All",
			"https://outlook.office.com/SMTP.Send",
			"openid",
			"email",
			"profile",
		],
		"query_parameters": {"prompt": "select_account"},
	},
	"google": {
		"authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
		"token_url": "https://oauth2.googleapis.com/token",
		"scopes": ["https://mail.google.com/", "openid", "email", "profile"],
		# a refresh token comes back only with offline access, and again only on consent
		"query_parameters": {"access_type": "offline", "prompt": "select_account consent"},
	},
	"yahoo": {
		"authorize_url": "https://api.login.yahoo.com/oauth2/request_auth",
		"token_url": "https://api.login.yahoo.com/oauth2/get_token",
		"scopes": ["mail-w", "openid", "email"],
		"query_parameters": {},
	},
	"yandex": {
		"authorize_url": "https://oauth.yandex.com/authorize",
		"token_url": "https://oauth.yandex.com/token",
		"scopes": ["mail:imap_full", "mail:smtp", "login:email"],
		"query_parameters": {},
	},
}


def ensure_email_oauth_providers() -> None:
	"""Add a record for each default provider that has none; never touches an existing one."""
	for provider, config in DEFAULT_PROVIDERS.items():
		if frappe.db.exists(PROVIDER, provider):
			continue
		# Runs from the install, migrate and test hooks, which have no signed-in user
		frappe.get_doc(
			{
				"doctype": PROVIDER,
				"provider": provider,
				"authorize_url": config["authorize_url"],
				"token_url": config["token_url"],
				"scopes": [{"scope": scope} for scope in config["scopes"]],
				"query_parameters": [{"key": k, "value": v} for k, v in config["query_parameters"].items()],
			}
		).insert(ignore_permissions=True)
