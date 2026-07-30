from __future__ import annotations

import time

import frappe
import jwt

from central.central.doctype.central_sso_settings.central_sso_settings import ALGORITHM, CentralSSOSettings

# Central signs every downward token — the bench-login SID and the first-boot enrollment
# token — with its single RSA key. Benches verify offline against the published JWKS, so a
# compromised bench (holding only the public key) can forge nothing. `aud` scopes a token to
# one deployment (its VM resource_id), so a SID minted for bench A is rejected by bench B.

BENCH_LOGIN_TTL = 5 * 60  # a short-lived, single-use admin SID
BOOTSTRAP_TTL = 30 * 60  # the first-boot enrollment window
ENROLL_SCOPE = "enroll"


def central_url() -> str:
	return frappe.conf.get("central_url") or frappe.utils.get_url()


def jwks_url() -> str:
	"""Where a bench fetches Central's public key(s) to verify minted tokens."""
	return f"{central_url()}/api/method/central.api.jwks.get_jwks"


def bench_gateway() -> str:
	"""The dev bench's gateway base, used when opening by explicit gateway (no Asset). The
	SID rides `/?sid=`, which the bench SPA consumes and exchanges at POST /api/login."""
	return (frappe.conf.get("bench_sso_redirect") or "http://localhost:3030").rstrip("/")


def mint_bench_login(audience: str) -> str:
	"""A short-lived admin SID that opens a bench. The bench verifies it against the JWKS
	and checks `aud` equals its own audience id."""
	return _mint(audience, {"sub": "admin", "scope": "bench"}, BENCH_LOGIN_TTL)


def mint_site_login(audience: str, site: str) -> str:
	"""A one-time assertion the site's pilot exchanges for an Administrator session, scoped to
	one site. `aud` is the hosting bench's audience id; the pilot verifies it against the JWKS."""
	return _mint(audience, {"sub": "admin", "scope": "site", "site": site}, BENCH_LOGIN_TTL)


def mint_bootstrap_token(team: str, pilot_credential_id: str) -> str:
	"""A single-use enrollment token seeded into a VM at create time. The pilot presents it
	once to `central.api.pilot.enroll` to fetch its long-lived credential.

	`aud` is the `pilot_credential_id` — the per-deployment audience id. Central controls it
	up front (the VM's resource_id isn't known until Atlas provisions), so it doubles as the
	audience every downward token to this bench will carry."""
	return _mint(pilot_credential_id, {"scope": ENROLL_SCOPE, "team": team}, BOOTSTRAP_TTL)


def verify_bootstrap_token(token: str) -> dict:
	"""Validate an enrollment token with Central's own public key and return the grant it
	carries: ``{team, pcid, jti}`` (pcid = the `aud`). Raises on a bad/expired/wrong-scope
	token."""
	from cryptography.hazmat.primitives.serialization import load_pem_public_key

	settings = CentralSSOSettings.instance()
	if not settings.public_key:
		frappe.throw("Central signing key is not initialised.", frappe.ValidationError)
	try:
		claims = jwt.decode(
			token,
			load_pem_public_key(settings.public_key.encode()),
			algorithms=[ALGORITHM],
			options={"verify_aud": False, "require": ["exp", "aud", "jti"]},
		)
	except jwt.InvalidTokenError as exc:
		frappe.throw(f"Invalid enrollment token: {exc}", frappe.AuthenticationError)
	if claims.get("scope") != ENROLL_SCOPE:
		frappe.throw("Not an enrollment token.", frappe.AuthenticationError)
	return {"team": claims["team"], "pcid": claims["aud"], "jti": claims["jti"]}


def _mint(audience: str, claims: dict, ttl: int) -> str:
	private_pem, kid = CentralSSOSettings.instance().signing_key()
	now = int(time.time())
	payload = {
		"iss": central_url(),
		"aud": audience,
		"iat": now,
		"exp": now + ttl,
		"jti": frappe.generate_hash(length=16),
		**claims,
	}
	return jwt.encode(payload, private_pem, algorithm=ALGORITHM, headers={"kid": kid})
