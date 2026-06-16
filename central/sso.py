from __future__ import annotations

import json
import time

import frappe
import jwt

from central.iam import CAPABILITY_VERSION, can, get_user_team_names, resolve_user_grants

# The bench admin backend verifies these assertions (HS256, audience=client_id,
# issuer=central_url, requiring exp/aud/iss/sub). Keep the mint in lockstep.
APP_NAME = "local-bench"  # OAuth Client we look up / create
ASSERTION_TTL = 60  # seconds — short-lived, stateless


def _central_url() -> str:
	return frappe.conf.get("central_url") or frappe.utils.get_url()


def _bench_sso_url() -> str:
	"""The bench's /sso endpoint. Until the Asset registry lands (#28) this is the
	dev target; get_bench_link accepts an explicit gateway_url to override it."""
	return frappe.conf.get("bench_sso_redirect") or "http://localhost:3030/sso"


def _ensure_oauth_client():
	"""The `local-bench` OAuth Client — the shared-secret trust anchor. Idempotent."""
	name = frappe.db.get_value("OAuth Client", {"app_name": APP_NAME})
	if name:
		return frappe.get_doc("OAuth Client", name)
	return frappe.get_doc(
		{
			"doctype": "OAuth Client",
			"app_name": APP_NAME,
			"default_redirect_uri": _bench_sso_url(),
			"grant_type": "Authorization Code",
			"response_type": "Code",
			"scopes": "openid",
			"skip_authorization": 1,
		}
	).insert(ignore_permissions=True)


def _bench_caps(user: str, team: str) -> list[str]:
	"""The user's bench-plane capabilities on a team — the only caps the bench enforces."""
	bench_plane = set(frappe.get_all("Capability", filters={"plane": "bench"}, pluck="name"))
	granted = {c for g in resolve_user_grants(user).get(team, []) for c in g.get("caps", [])}
	return sorted(granted & bench_plane)


def mint_bench_assertion(user: str, team: str) -> str:
	client = _ensure_oauth_client()
	now = int(time.time())
	payload = {
		"sub": user,
		"team": team,
		"caps": _bench_caps(user, team),
		"cap_version": CAPABILITY_VERSION,
		"aud": client.client_id,
		"iss": _central_url(),
		"iat": now,
		"exp": now + ASSERTION_TTL,
	}
	return jwt.encode(payload, client.client_secret, algorithm="HS256")


@frappe.whitelist(methods=["GET"])
def get_bench_link(team: str | None = None, gateway_url: str | None = None) -> dict:
	"""Mint a scoped SSO assertion and return the bench URL to redirect to.

	`vm:open` on the team is the gate. The target bench is passed in (the VM's
	gateway_url, wired in #28) or falls back to the `bench_sso_redirect` config.
	"""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw("Sign in first.", frappe.PermissionError)
	team = team or _only_team(user)
	if not can(user, team, "vm:open"):
		frappe.throw("You can't open benches for this team.", frappe.PermissionError)
	target = (gateway_url or _bench_sso_url()).rstrip("/")
	if not target.endswith("/sso"):
		target += "/sso"
	return {"url": f"{target}?assertion={mint_bench_assertion(user, team)}"}


def _only_team(user: str) -> str:
	teams = get_user_team_names(user)
	if len(teams) != 1:
		frappe.throw("Specify a team.", frappe.ValidationError)
	return teams[0]


def print_local_bench_credentials() -> None:
	"""Emit the bench's SSO trust config for admin/scripts/setup_sso.sh to capture."""
	client = _ensure_oauth_client()
	frappe.db.commit()
	cfg = {
		"central_url": _central_url(),
		"client_id": client.client_id,
		"client_secret": client.client_secret,
	}
	print(f"SSO_CONFIG={json.dumps(cfg)}")
