import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_to_date, get_datetime, now_datetime

from central.api.openapi import PUBLIC_API
from central.iam import expand_capabilities, is_active_team_member, is_api_key_request

# What each scope level grants. Write includes Read, and every level stays inside the user's role:
# `iam.resolve_user_grants` intersects the two. `server:console` is left out, so a key never opens
# an Administrator session on a bench.
SCOPES = {
	"Servers": {
		"Read": ("server:view", "cluster:view"),
		"Write": (
			"server:create",
			"server:power",
			"server:resize",
			"server:terminate",
			"server:snapshot",
			"server:network",
			"server:ssh-key",
			"server:wireguard",
		),
	},
	"Support": {"Write": ("support:view",)},
}
EXPIRY_DAYS = (1, 7, 30, 90, 365)

# A key reaches the public API only, minus what would let a leaked key widen its own reach:
# team members, roles and invitations, and the profile. The key endpoints are not public at all.
KEY_EXCLUDED_METHODS = frozenset(("central.api.identity.update_profile",))
KEY_METHODS = (
	frozenset(
		f"central.api.{module}.{name}"
		for module, (_title, _about, names) in PUBLIC_API.items()
		if module != "teams"
		for name in names
	)
	- KEY_EXCLUDED_METHODS
)
METHOD_PATH = re.compile(r"/api/(?:v[12]/)?method/([\w.]+)/?")
LAST_USED_INTERVAL_MINUTES = 5


class APIKey(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from central.identity.doctype.api_key_scope.api_key_scope import APIKeyScope

		api_key: DF.Data | None
		api_secret: DF.Password | None
		enabled: DF.Check
		expires_at: DF.Datetime
		last_used_at: DF.Datetime | None
		scopes: DF.Table[APIKeyScope]
		team: DF.Link
		title: DF.Data
		user: DF.Link
	# end: auto-generated types

	def before_insert(self) -> None:
		self.api_key = frappe.generate_hash(length=20)

	def validate(self) -> None:
		if not is_active_team_member(self.user, self.team):
			frappe.throw(_("You can create a key only for a team you are an active member of."))

		self.validate_scopes()
		if self.is_new():
			self.validate_expiry()

	def validate_expiry(self) -> None:
		"""Every path that inserts a key, the route and `/api/resource` alike, gets the same limit."""
		expires_at = get_datetime(self.expires_at)
		if expires_at <= now_datetime():
			frappe.throw(_("The expiry must be in the future."))
		if expires_at > add_to_date(now_datetime(), days=max(EXPIRY_DAYS), minutes=1):
			frappe.throw(_("A key can live at most {0} days.").format(max(EXPIRY_DAYS)))

	def validate_scopes(self) -> None:
		categories = [row.category for row in self.scopes]
		if not categories or len(categories) != len(set(categories)):
			frappe.throw(_("Give each category one level, and at least one category."))

		for row in self.scopes:
			if row.access not in SCOPES[row.category]:
				frappe.throw(_("{0} has no {1} level.").format(row.category, row.access))

	def get_capabilities(self) -> frozenset[str]:
		"""The capabilities the scopes grant. Write includes the category's Read."""
		capabilities = []
		for row in self.scopes:
			levels = SCOPES[row.category]
			capabilities += levels.get("Read", ())
			if row.access == "Write":
				capabilities += levels["Write"]

		return frozenset(expand_capabilities(capabilities))

	@property
	def is_expired(self) -> bool:
		return get_datetime(self.expires_at) <= now_datetime()


def get_expiry(days: int):
	if days not in EXPIRY_DAYS:
		frappe.throw(_("Choose an expiry of {0} days.").format(", ".join(map(str, EXPIRY_DAYS))))

	return add_to_date(now_datetime(), days=days)


def on_doctype_update() -> None:
	frappe.db.add_index("API Key", ["user", "creation"])


def authenticate() -> None:
	"""Narrow a request signed with an API Key. Frappe has already checked the key and the secret.

	1. A request that does not name this DocType as its authorization source is not a key request.
	2. An expired key, or a key of a disabled user, is refused.
	3. A key reaches only the methods listed above.
	4. Every capability check in the request then sees only the key's team and scopes."""
	if not is_api_key_request():
		return
	if frappe.session.user in ("", "Guest"):
		return

	key = get_request_key()
	if not is_key_method(frappe.request.path):
		frappe.throw(_("An API key cannot call this method."), frappe.PermissionError)

	frappe.local.api_key = frappe._dict(team=key.team, capabilities=key.get_capabilities())
	_record_use(key)


def get_request_key() -> APIKey:
	"""The key named in the token. An expired key, or a key of a disabled user, is refused."""
	scheme, _space, token = frappe.get_request_header("Authorization", "").partition(" ")
	if scheme.lower() != "token":
		raise frappe.AuthenticationError

	key = frappe.get_doc("API Key", {"api_key": token.split(":", 1)[0], "enabled": 1})
	if key.user != frappe.session.user or key.is_expired:
		raise frappe.AuthenticationError
	if not frappe.get_cached_value("User", key.user, "enabled"):
		raise frappe.AuthenticationError

	return key


def is_key_method(path: str) -> bool:
	match = METHOD_PATH.fullmatch(path)
	method = match.group(1) if match else ""
	return method in KEY_METHODS


def _record_use(key: APIKey) -> None:
	last_used = key.last_used_at and get_datetime(key.last_used_at)
	if last_used and last_used > add_to_date(now_datetime(), minutes=-LAST_USED_INTERVAL_MINUTES):
		return

	key.db_set("last_used_at", now_datetime(), update_modified=False)
	# Frappe rolls back a GET request unless this flag is set, and most key calls are reads.
	frappe.local.flags.commit = True
