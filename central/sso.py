from __future__ import annotations

import json
import time

import frappe
import jwt

from central.iam import CAPABILITY_VERSION, resolve_user_grants

# The bench admin backend verifies these assertions (HS256, audience=client_id,
# issuer=central_url, requiring exp/aud/iss/sub). Keep the mint in lockstep.
APP_NAME = "local-bench"  # OAuth Client we look up / create
ASSERTION_TTL = 60  # seconds — short-lived, stateless


def _central_url() -> str:
	return frappe.conf.get("central_url") or frappe.utils.get_url()


def _insecure_hs256_allowed() -> bool:
	"""Explicit opt-in dev switch. Default (unset) is off, so the shared-secret path
	can never ship to prod by accident — a dev site sets `sso_allow_insecure_hs256`."""
	return bool(frappe.conf.get("sso_allow_insecure_hs256"))


def _bench_sso_url() -> str:
	"""The bench's /sso endpoint. Until the Asset registry lands (#28) this is the
	dev target; get_bench_link accepts an explicit gateway_url to override it."""
	configured = frappe.conf.get("bench_sso_redirect")
	if configured:
		return configured
	if not _insecure_hs256_allowed():
		frappe.throw(
			"No bench gateway configured — pass gateway_url or set bench_sso_redirect.",
			frappe.ValidationError,
		)
	return "http://localhost:3030/sso"


def _assert_insecure_signing_allowed() -> None:
	"""Fail closed. Until RS256/JWKS (#21) lands, the mint uses a shared HS256 secret
	— forgeable by any bench that holds it, so it is gated on the explicit
	`sso_allow_insecure_hs256` flag and stays broken in prod until real signing
	replaces it."""
	if not _insecure_hs256_allowed():
		frappe.throw(
			"Refusing to mint a shared-secret (HS256) SSO assertion: set "
			"sso_allow_insecure_hs256 in dev, or land RS256 signing (#21) for prod.",
			frappe.ValidationError,
		)


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
	_assert_insecure_signing_allowed()
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


def print_local_bench_credentials() -> None:
	"""Emit the bench's SSO trust config for admin/scripts/setup_sso.sh to capture."""
	_assert_insecure_signing_allowed()
	client = _ensure_oauth_client()
	# CLI helper: persist the just-created OAuth Client so the external setup script
	# can read its credentials from stdout in a separate connection.
	frappe.db.commit()
	cfg = {
		"central_url": _central_url(),
		"client_id": client.client_id,
		"client_secret": client.client_secret,
	}
	print(f"SSO_CONFIG={json.dumps(cfg)}")
